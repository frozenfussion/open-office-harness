// SPDX-License-Identifier: AGPL-3.0-only
using System.Diagnostics;
using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using ControlCentre.Platform;

namespace ControlCentre.Registry;

public sealed record ConnectionResult(bool Ok, long DurationMs, string? Reason = null, int? ProviderStatus = null,
  string? ProviderMessage = null, string? ModelTitle = null, string? Reply = null, int InputTokens = 0, int OutputTokens = 0, decimal CostUsd = 0, decimal? Score = null)
{
  public JsonObject View() => Ok ? new JsonObject
  {
    ["ok"] = true,
    ["model_title"] = ModelTitle,
    ["reply"] = Reply,
    ["score"] = Score,
    ["duration_ms"] = DurationMs,
    ["usage"] = new JsonObject { ["input_tokens"] = InputTokens, ["output_tokens"] = OutputTokens },
    ["cost_usd"] = CostUsd
  } : new JsonObject { ["ok"] = false, ["reason"] = Reason, ["provider_status"] = ProviderStatus, ["provider_message"] = ProviderMessage };
}

public sealed class ModelConnection(HttpClient http, IConfiguration config, TimeProvider clock, ModelKeys keys, ILogger<ModelConnection> logger)
{
  private readonly SemaphoreSlim tokenLock = new(1, 1);
  private string? token;
  private DateTimeOffset tokenExpires;
  public async Task<ConnectionResult> Test(ModelEntry entry, string actor, CancellationToken ct)
  {
    var watch = Stopwatch.StartNew();
    ConnectionResult Failure(string reason, int? status = null, string? message = null) => new(false, watch.ElapsedMilliseconds, reason, status, message);
    if (string.IsNullOrEmpty(config["CC_CLIENT_SECRET"])) return Failure("the Control Centre has no service credentials");
    using var limit = CancellationTokenSource.CreateLinkedTokenSource(ct);
    limit.CancelAfter(TimeSpan.FromSeconds(entry.TimeoutSeconds + 10));
    try
    {
      var key = keys.Decrypt(entry.Id, entry.ApiKeyEncrypted!);
      var accessToken = await Token(limit.Token);
      if (accessToken is null) return Failure("the Control Centre could not sign in to the Gateway");
      using var request = new HttpRequestMessage(HttpMethod.Post, (config["CC_GATEWAY_URL"] ?? "").TrimEnd('/') + (entry.Purpose == "classification" ? "/v1/classify" : "/v1/call"));
      request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", accessToken);
      var body = new JsonObject
      {
        ["purpose"] = entry.Purpose,
        ["model_entry_id"] = entry.Id.ToString(),
        ["user_id"] = "admin-test-" + actor,
        ["messages"] = new JsonArray(new JsonObject { ["role"] = "user", ["content"] = "Reply with the single word OK." }),
        ["stream"] = false
      };
      if (entry.Tier is not null) body["tier"] = entry.Tier;
      if (entry.Purpose == "classification") body = new JsonObject
      {
        ["model_entry_id"] = entry.Id.ToString(),
        ["user_id"] = "admin-test-" + actor,
        ["text"] = "This is a connection test.",
        ["questions"] = new JsonObject { ["test"] = "Is this a connection test?" }
      };
      request.Content = JsonContent.Create(body);
      request.Options.Set(Tracing.InternalRequest, true);
      using var response = await http.SendAsync(request, limit.Token);
      if (response.StatusCode is HttpStatusCode.Unauthorized or HttpStatusCode.Forbidden)
      {
        SetupError();
        return Failure("the Control Centre could not sign in to the Gateway");
      }
      var answer = await response.Content.ReadFromJsonAsync<JsonObject>(cancellationToken: limit.Token);
      if (answer is null) return Failure("unexpected answer");
      if (response.IsSuccessStatusCode)
      {
        if (response.StatusCode != HttpStatusCode.OK || (entry.Purpose != "classification" && Text(answer, "content") is not { Length: > 0 }) ||
          Text(answer, "model_entry_id") != entry.Id.ToString() || Text(answer, "model_title") is not { } title ||
          answer["usage"] is not JsonObject usage || !Number<int>(usage, "input_tokens", out var input) || input < 0 ||
          !Number<int>(usage, "output_tokens", out var output) || output < 0 || !Number<decimal>(answer, "cost_usd", out var cost) || cost < 0)
          return Failure("unexpected answer");
        decimal? score = null;
        if (entry.Purpose == "classification")
        {
          if (answer["scores"] is not JsonObject scores || !Number<decimal>(scores, "test", out var n) || n is < 0 or > 1) return Failure("unexpected answer");
          score = n;
        }
        return new(true, watch.ElapsedMilliseconds, ModelTitle: Redact(title, key), Reply: Redact(Text(answer, "content") ?? "", key), InputTokens: input, OutputTokens: output, CostUsd: cost, Score: score);
      }
      int? status = Number<int>(answer, "provider_status", out var providerStatus) && providerStatus is >= 100 and <= 599 ? providerStatus : null;
      var code = Text(answer, "code");
      if (code != "unavailable") status = null;
      var rawMessage = code == "unavailable" ? Text(answer, "provider_message") : null;
      var reason = code switch
      {
        "no_model" => "entry is not active or its connection type is not supported",
        "rate_limited" => "over this entry's rate limit; wait a minute",
        "budget_exceeded" => "over its daily budget today",
        "registry_unavailable" => "the Control Centre registry did not answer",
        "unavailable" => status switch
        {
          401 or 403 => "key refused",
          402 => "the provider account has no credit",
          404 => "model or endpoint not found",
          429 => "rate limited by the provider",
          null when rawMessage == "time limit reached" => "took longer than its time limit",
          null when rawMessage == "could not connect" => "could not reach the endpoint",
          _ => "unexpected answer"
        },
        _ => "unexpected answer"
      };
      var message = rawMessage is null ? null : Redact(rawMessage, key);
      if (message?.Length > 300) message = message[..300];
      return Failure(reason, status, message);
    }
    catch (OperationCanceledException) { return Failure("took longer than its time limit"); }
    catch (HttpRequestException) { return Failure("could not reach the endpoint"); }
    catch (Exception e) when (e is JsonException or InvalidOperationException or FormatException or ArgumentException or ApiException)
    { return Failure("unexpected answer"); }
  }
  public async Task<string?> Token(CancellationToken ct)
  {
    await tokenLock.WaitAsync(ct);
    try
    {
      if (token is not null && clock.GetUtcNow() < tokenExpires.AddSeconds(-30)) return token;
      try
      {
        using var request = new HttpRequestMessage(HttpMethod.Post, (config["CC_OIDC_ISSUER"] ?? "").TrimEnd('/') + "/protocol/openid-connect/token")
        {
          Content = new FormUrlEncodedContent(new Dictionary<string, string>
          { ["grant_type"] = "client_credentials", ["client_id"] = "ooh-control-centre", ["client_secret"] = config["CC_CLIENT_SECRET"]! })
        };
        request.Options.Set(Tracing.InternalRequest, true);
        using var response = await http.SendAsync(request, ct);
        if (response.IsSuccessStatusCode)
        {
          var body = await response.Content.ReadFromJsonAsync<JsonObject>(cancellationToken: ct);
          if (body is not null && Text(body, "access_token") is { Length: > 0 } access && Number<int>(body, "expires_in", out var expires) && expires > 0)
          {
            token = access; tokenExpires = clock.GetUtcNow().AddSeconds(expires); return token;
          }
        }
      }
      catch (Exception e) when (e is HttpRequestException or JsonException or InvalidOperationException or FormatException or ArgumentException) { }
      SetupError(); return null;
    }
    finally { tokenLock.Release(); }
  }
  private void SetupError() => logger.LogWarning("Model connection test setup error: the Control Centre could not sign in to the Gateway");
  private static string? Text(JsonObject value, string field) => value[field] is JsonValue v && v.TryGetValue<string>(out var text) ? text : null;
  private static bool Number<T>(JsonObject value, string field, out T number)
  {
    number = default!;
    return value[field] is JsonValue v && v.TryGetValue(out number!);
  }
  public static string Redact(string text, string key)
  {
    var marked = new bool[text.Length]; var lengths = new int[key.Length + 1];
    foreach (Match match in Regex.Matches(text, @"sk-(?:ant-)?[A-Za-z0-9_-]+")) Array.Fill(marked, true, match.Index, match.Length);
    if (key.Length > 0)
      for (var at = text.IndexOf(key, StringComparison.Ordinal); at >= 0; at = text.IndexOf(key, at + 1, StringComparison.Ordinal))
        Array.Fill(marked, true, at, key.Length);
    // Mark all overlaps in the original text so one replacement cannot hide another secret.
    for (var i = 0; i < text.Length; i++)
      for (var j = key.Length; j > 0; j--)
      {
        lengths[j] = text[i] == key[j - 1] ? lengths[j - 1] + 1 : 0;
        if (lengths[j] >= 8) Array.Fill(marked, true, i - lengths[j] + 1, lengths[j]);
      }
    var safe = new StringBuilder();
    for (var i = 0; i < text.Length; i++)
      if (!marked[i]) safe.Append(text[i]);
      else { safe.Append("[removed]"); while (i + 1 < text.Length && marked[i + 1]) i++; }
    return safe.ToString();
  }
}
