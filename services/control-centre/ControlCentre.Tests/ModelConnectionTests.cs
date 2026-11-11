// SPDX-License-Identifier: AGPL-3.0-only
using System.Net;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json.Nodes;
using ControlCentre.Platform;
using ControlCentre.Registry;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Xunit;

namespace ControlCentre.Tests;

public sealed class TestClock : TimeProvider
{
  public DateTimeOffset Now { get; set; } = DateTimeOffset.UtcNow;
  public override DateTimeOffset GetUtcNow() => Now;
}
public sealed class TestGatewayHttp : HttpMessageHandler
{
  public int TokenCalls { get; private set; }
  public int GatewayCalls { get; private set; }
  public string? TokenBody { get; private set; }
  public string? TokenUrl { get; private set; }
  public JsonObject? GatewayBody { get; private set; }
  public string? Authorization { get; private set; }
  public string? GatewayUrl { get; private set; }
  public HttpStatusCode TokenStatus { get; set; } = HttpStatusCode.OK;
  public Func<CancellationToken, Task<HttpResponseMessage>>? Answer { get; set; }
  protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
  {
    if (request.RequestUri!.AbsolutePath.EndsWith("/protocol/openid-connect/token", StringComparison.Ordinal))
    {
      TokenCalls++; TokenUrl = request.RequestUri.ToString(); TokenBody = await request.Content!.ReadAsStringAsync(ct);
      return new HttpResponseMessage(TokenStatus) { Content = JsonContent.Create(new { access_token = "synthetic-service-token", expires_in = 300 }) };
    }
    GatewayUrl = request.RequestUri.AbsolutePath; GatewayCalls++; Authorization = request.Headers.Authorization?.ToString();
    GatewayBody = request.Content is null ? null : await request.Content.ReadFromJsonAsync<JsonObject>(ct);
    if (Answer is not null) return await Answer(ct);
    if (GatewayUrl == "/v1/classify") return new HttpResponseMessage(HttpStatusCode.OK) { Content = JsonContent.Create(new { scores = new { test = 0.9m }, model_entry_id = GatewayBody!["model_entry_id"]!.GetValue<string>(), model_title = "Synthetic model", usage = new { input_tokens = 2, output_tokens = 1 }, cost_usd = 0.000123m }) };
    return Success(GatewayBody!["model_entry_id"]!.GetValue<string>());
  }
  public static HttpResponseMessage Success(string id, string reply = "synthetic reply") => new(HttpStatusCode.OK)
  {
    Content = JsonContent.Create(new { content = reply, model_entry_id = id, model_title = "Synthetic model", usage = new { input_tokens = 2, output_tokens = 1 }, cost_usd = 0.000123m })
  };
  public static HttpResponseMessage Error(int httpStatus, string code, int? status = null, string? message = null) => new((HttpStatusCode)httpStatus)
  { Content = JsonContent.Create(new { code, message = "Synthetic Gateway error", provider_status = status, provider_message = message }) };
}

public sealed class ModelConnectionTests
{
  private sealed class Fixture : IDisposable
  {
    public const string ProviderKey = "fixture-provider-abcdefgh12345678-ijklmnop";
    public TestGatewayHttp Transport { get; } = new();
    public TestClock Clock { get; } = new();
    public TestLogs Logs { get; } = new();
    public ModelEntry Entry { get; } = new() { Purpose = "chat", Tier = 3, TimeoutSeconds = 10 };
    public ModelConnection Connection { get; }
    private readonly HttpClient http;
    private readonly ILoggerFactory logging;
    public Fixture(string secret = "synthetic-client-secret+&")
    {
      var keys = new ModelKeys(Convert.ToBase64String(new byte[32]));
      Entry.ApiKeyEncrypted = keys.Encrypt(Entry.Id, ProviderKey);
      var config = new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?>
      { ["CC_CLIENT_SECRET"] = secret, ["CC_OIDC_ISSUER"] = "https://issuer.invalid/realms/ooh", ["CC_GATEWAY_URL"] = "http://gateway.invalid:8080" }).Build();
      http = new HttpClient(Transport) { Timeout = Timeout.InfiniteTimeSpan };
      logging = LoggerFactory.Create(builder => builder.AddProvider(Logs));
      Connection = new ModelConnection(http, config, Clock, keys, logging.CreateLogger<ModelConnection>());
    }
    public Task<ConnectionResult> Test() => Connection.Test(Entry, "synthetic-admin", TestContext.Current.CancellationToken);
    public void Dispose() { http.Dispose(); logging.Dispose(); }
  }
  [Fact]
  public async Task SuccessUsesOnlyPinnedFixedCallAndPrivateTokenForm()
  {
    using var f = new Fixture(); var result = await f.Test();
    Assert.True(result.Ok); Assert.Equal("synthetic reply", result.Reply); Assert.Equal(2, result.InputTokens); Assert.Equal(1, result.OutputTokens); Assert.Equal(0.000123m, result.CostUsd);
    Assert.Equal("https://issuer.invalid/realms/ooh/protocol/openid-connect/token", f.Transport.TokenUrl);
    Assert.Equal("grant_type=client_credentials&client_id=ooh-control-centre&client_secret=synthetic-client-secret%2B%26", f.Transport.TokenBody);
    Assert.Equal("Bearer synthetic-service-token", f.Transport.Authorization);
    var body = f.Transport.GatewayBody!;
    Assert.Equal(f.Entry.Id.ToString(), body["model_entry_id"]!.GetValue<string>());
    Assert.Equal("admin-test-synthetic-admin", body["user_id"]!.GetValue<string>());
    Assert.Equal("chat", body["purpose"]!.GetValue<string>()); Assert.Equal(3, body["tier"]!.GetValue<int>());
    Assert.False(body["stream"]!.GetValue<bool>()); Assert.False(body.ContainsKey("tools")); Assert.Equal(6, body.Count);
    Assert.Equal("[{\"role\":\"user\",\"content\":\"Reply with the single word OK.\"}]", body["messages"]!.ToJsonString());
    Assert.DoesNotContain(Fixture.ProviderKey, body.ToJsonString()); Assert.Empty(f.Logs.Entries);
  }
  [Fact]
  public async Task ClassificationTestUsesOnlyPinnedFixedQuestionAndReturnsScore()
  {
    using var f = new Fixture(); f.Entry.Purpose = "classification"; f.Entry.Tier = null;
    var result = await f.Test(); Assert.True(result.Ok); Assert.Equal(0.9m, result.Score); Assert.Equal("/v1/classify", f.Transport.GatewayUrl);
    var body = f.Transport.GatewayBody!; Assert.Equal(4, body.Count);
    Assert.Equal("admin-test-synthetic-admin", body["user_id"]!.GetValue<string>());
    Assert.Equal(f.Entry.Id.ToString(), body["model_entry_id"]!.GetValue<string>());
    Assert.Equal("This is a connection test.", body["text"]!.GetValue<string>());
    Assert.Equal("Is this a connection test?", body["questions"]!["test"]!.GetValue<string>());
    foreach (var score in new[] { -0.1m, 1.1m })
    {
      f.Transport.Answer = _ => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = JsonContent.Create(new { scores = new { test = score }, model_entry_id = f.Entry.Id, model_title = "Synthetic", usage = new { input_tokens = 1, output_tokens = 1 }, cost_usd = 0 }) });
      Assert.False((await f.Test()).Ok);
    }
  }
  [Theory]
  [InlineData(404, "no_model", 401, "entry is not active or its connection type is not supported")]
  [InlineData(429, "rate_limited", null, "over this entry's rate limit; wait a minute")]
  [InlineData(503, "budget_exceeded", 401, "over its daily budget today")]
  [InlineData(503, "registry_unavailable", null, "the Control Centre registry did not answer")]
  [InlineData(503, "unavailable", 401, "key refused")]
  [InlineData(503, "unavailable", 403, "key refused")]
  [InlineData(503, "unavailable", 402, "the provider account has no credit")]
  [InlineData(503, "unavailable", 404, "model or endpoint not found")]
  [InlineData(503, "unavailable", 429, "rate limited by the provider")]
  [InlineData(503, "unavailable", 500, "unexpected answer")]
  [InlineData(503, "unknown", 401, "unexpected answer")]
  public async Task GatewayCodeTakesPriorityThenProviderStatus(int httpStatus, string code, int? providerStatus, string reason)
  {
    using var f = new Fixture(); f.Transport.Answer = _ => Task.FromResult(TestGatewayHttp.Error(httpStatus, code, providerStatus, "synthetic provider detail"));
    var result = await f.Test(); Assert.False(result.Ok); Assert.Equal(reason, result.Reason);
    Assert.Equal(code == "unavailable" ? providerStatus : null, result.ProviderStatus);
    Assert.DoesNotContain(f.Logs.Entries, line => line.Contains("synthetic provider detail", StringComparison.Ordinal));
    Assert.True(result.View().ContainsKey("provider_status")); Assert.True(result.View().ContainsKey("provider_message"));
  }
  [Theory]
  [InlineData("time limit reached", "took longer than its time limit")]
  [InlineData("could not connect", "could not reach the endpoint")]
  [InlineData("other", "unexpected answer")]
  public async Task GatewayTransportReasons(string message, string reason)
  {
    using var f = new Fixture(); f.Transport.Answer = _ => Task.FromResult(TestGatewayHttp.Error(503, "unavailable", message: message));
    Assert.Equal(reason, (await f.Test()).Reason);
  }
  [Theory]
  [InlineData(401)]
  [InlineData(403)]
  public async Task GatewayAuthenticationFailureLogsOnlyOneSetupError(int status)
  {
    using var f = new Fixture(); f.Transport.Answer = _ => Task.FromResult(TestGatewayHttp.Error(status, "unavailable", 401, Fixture.ProviderKey));
    Assert.Equal("the Control Centre could not sign in to the Gateway", (await f.Test()).Reason);
    var log = Assert.Single(f.Logs.Entries); Assert.Contains("setup error", log); Assert.DoesNotContain(Fixture.ProviderKey, log);
  }
  [Fact]
  public async Task TokenCachedUntilThirtySecondsBeforeExpiry()
  {
    using var f = new Fixture(); Assert.True((await f.Test()).Ok);
    f.Clock.Now = f.Clock.Now.AddSeconds(269); Assert.True((await f.Test()).Ok); Assert.Equal(1, f.Transport.TokenCalls);
    f.Clock.Now = f.Clock.Now.AddSeconds(1); Assert.True((await f.Test()).Ok); Assert.Equal(2, f.Transport.TokenCalls);
  }
  [Fact]
  public async Task MissingAndRefusedCredentialsFailWithoutCallingGateway()
  {
    using (var f = new Fixture(""))
    {
      Assert.Equal("the Control Centre has no service credentials", (await f.Test()).Reason);
      Assert.Equal(0, f.Transport.TokenCalls); Assert.Equal(0, f.Transport.GatewayCalls);
    }
    using (var f = new Fixture())
    {
      f.Transport.TokenStatus = HttpStatusCode.Unauthorized;
      Assert.Equal("the Control Centre could not sign in to the Gateway", (await f.Test()).Reason);
      Assert.Equal(0, f.Transport.GatewayCalls); Assert.Single(f.Logs.Entries);
    }
  }
  [Theory]
  [InlineData(true, "took longer than its time limit")]
  [InlineData(false, "could not reach the endpoint")]
  public async Task OwnHttpTimeoutAndConnectionErrors(bool timeout, string reason)
  {
    using var f = new Fixture(); f.Transport.Answer = ct => { if (timeout) throw new OperationCanceledException(ct); throw new HttpRequestException("synthetic private detail"); };
    Assert.Equal(reason, (await f.Test()).Reason); Assert.Empty(f.Logs.Entries);
  }
  [Fact]
  public async Task UnexpectedBodiesAreSafeAndReplyAndProviderMessagesAreRedacted()
  {
    Assert.Equal("[removed]", ModelConnection.Redact("sk-abcdefgh12345678-other", "abcdefgh12345678"));
    Assert.Equal("[removed]", ModelConnection.Redact("sk-ant-synthetic-secret", "prefix-synthetic-secret-tail"));
    using var f = new Fixture();
    f.Transport.Answer = _ => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent("invalid JSON", Encoding.UTF8, "application/json") });
    Assert.Equal("unexpected answer", (await f.Test()).Reason);
    f.Transport.Answer = _ => Task.FromResult(TestGatewayHttp.Success(Guid.NewGuid().ToString()));
    Assert.Equal("unexpected answer", (await f.Test()).Reason);
    var message = Fixture.ProviderKey + " abcdefgh12345678 sk-ant-synthetic-secret sk-synthetic-key " + new string('x', 400);
    f.Transport.Answer = _ => Task.FromResult(TestGatewayHttp.Error(503, "unavailable", 401, message));
    var failure = await f.Test(); Assert.Equal(300, failure.ProviderMessage!.Length);
    Assert.DoesNotContain(Fixture.ProviderKey, failure.ProviderMessage); Assert.DoesNotContain("abcdefgh12345678", failure.ProviderMessage); Assert.DoesNotContain("sk-", failure.ProviderMessage);
    f.Transport.Answer = _ => Task.FromResult(TestGatewayHttp.Success(f.Entry.Id.ToString(), message));
    var success = await f.Test(); Assert.DoesNotContain(Fixture.ProviderKey, success.Reply!); Assert.DoesNotContain("sk-", success.Reply!); Assert.Empty(f.Logs.Entries);
  }
}
