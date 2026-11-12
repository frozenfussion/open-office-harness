// SPDX-License-Identifier: AGPL-3.0-only
using System.Globalization;
using System.Security.Claims;
using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.EntityFrameworkCore;

namespace ControlCentre.Platform;

public sealed class ApiException(int status, string code, string message) : Exception(message)
{
  public int Status { get; } = status;
  public string Code { get; } = code;
}

public static class Api
{
  public static readonly JsonSerializerOptions Json = new()
  {
    PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    DefaultIgnoreCondition = System.Text.Json.Serialization.JsonIgnoreCondition.WhenWritingNull
  };
  public static string Encode(object value) => JsonSerializer.Serialize(value, Json);
  public static IResult Error(int status, string code, string message) => Results.Json(new { code, message }, statusCode: status);
  public static void Require(bool valid, string message = "Invalid input")
  {
    if (!valid) throw new ApiException(400, "invalid_input", message);
  }
  public static void Found(bool found)
  {
    if (!found) throw new ApiException(404, "not_found", "Entry not found");
  }
  public static string Actor(HttpContext c) => c.User.FindFirstValue("sub") ?? throw new ApiException(401, "unauthorized", "Valid token required");
  public static Guid Correlation(HttpContext c) => (Guid)(c.Items["correlation_id"] ??= Guid.NewGuid());
  public static bool Admin(ClaimsPrincipal user)
  {
    var roles = user.FindFirstValue("realm_access");
    if (roles is null) return false;
    try { return JsonNode.Parse(roles)?["roles"]?.AsArray().Any(x => x?.GetValue<string>() == "ooh-admin") == true; }
    catch (JsonException) { return false; }
    catch (InvalidOperationException) { return false; }
  }
  public static bool Service(ClaimsPrincipal user, string client) => user.FindFirstValue("azp") == client;
  public static void Authorize(HttpContext c, string? userId = null, bool gateway = false)
  {
    var allowed = gateway ? Service(c.User, "ooh-model-gateway") :
        Admin(c.User) || (userId is not null && (Service(c.User, "ooh-harness-api") ||
            (!IsService(c.User) && Actor(c) == userId)));
    if (!allowed) throw new ApiException(403, "forbidden", "Operation not allowed");
  }
  public static bool IsService(ClaimsPrincipal user) => user.FindFirstValue("azp") is "ooh-harness-api" or "ooh-model-gateway" or "ooh-control-centre"
      || user.FindFirstValue("preferred_username")?.StartsWith("service-account-", StringComparison.Ordinal) == true;
  public static void Query(HttpContext c, params string[] allowed)
  {
    Require(c.Request.Query.All(x => allowed.Contains(x.Key) && x.Value.Count == 1), "Unknown or repeated query field");
  }
  public static string Text(string? text)
  {
    Require(!string.IsNullOrWhiteSpace(text));
    return text!;
  }
  public static string Q(HttpContext c, string name) => Text(c.Request.Query[name]);
  public static int Limit(HttpContext c)
  {
    if (!c.Request.Query.ContainsKey("limit")) return 50;
    Require(int.TryParse(c.Request.Query["limit"], out var value) && value is >= 1 and <= 200, "limit must be 1 to 200");
    return value;
  }
  public static Guid Id(string text)
  {
    Require(Guid.TryParse(text, out var id), "Invalid id");
    return id;
  }
  public static async Task<JsonObject> Body(HttpContext c, string[] required, params string[] optional)
  {
    Require(c.Request.HasJsonContentType(), "JSON body required");
    JsonDocument doc;
    try { doc = await JsonDocument.ParseAsync(c.Request.Body); }
    catch (JsonException) { throw new ApiException(400, "invalid_input", "Invalid JSON"); }
    using (doc)
    {
      Require(doc.RootElement.ValueKind == JsonValueKind.Object);
      var fields = doc.RootElement.EnumerateObject().Select(x => x.Name).ToArray();
      Require(fields.Distinct().Count() == fields.Length && fields.All(x => required.Contains(x) || optional.Contains(x)) && required.All(fields.Contains), "Unknown, duplicate or missing field");
      return JsonNode.Parse(doc.RootElement.GetRawText())!.AsObject();
    }
  }
  public static T Value<T>(JsonObject b, string key)
  {
    if (b[key] is JsonValue value && value.TryGetValue<T>(out var result)) return result;
    throw new ApiException(400, "invalid_input", "Invalid or missing " + key);
  }
  public static string String(JsonObject b, string key) => Text(Value<string>(b, key));
  public static void Stamp(BusinessRow row, string actor, bool created = false)
  {
    row.UpdatedAt = DateTimeOffset.UtcNow;
    row.UpdatedBy = actor;
    if (created) row.CreatedBy = actor;
  }
  public static async Task Remove<T>(HttpContext c, CentreDb db, T? row, string target) where T : BusinessRow
  {
    Found(row is not null && row.DeletedAt is null);
    var before = Encode(row is ControlCentre.Platform.ModelEntry model ? ControlCentre.Registry.RegistryRoutes.View(model) : row!);
    row!.DeletedAt = DateTimeOffset.UtcNow;
    Stamp(row, Actor(c));
    Change(db, Actor(c), typeof(T).Name.ToLowerInvariant() + ".removed", target, Correlation(c), new { before = JsonNode.Parse(before), after = row is ModelEntry entry ? ControlCentre.Registry.RegistryRoutes.View(entry) : (object)row });
    await db.SaveChangesAsync();
  }
  public static void Change(CentreDb db, string actor, string action, string target, Guid correlation, object detail, string? userId = null, string outcome = "success")
  {
    db.Audit.Add(new AuditRow { Actor = actor, Action = action, Target = target, CorrelationId = correlation, Detail = Encode(detail), Outcome = outcome });
    Event(db, "audit.events", "audit.event", correlation, userId ?? actor, new { actor, action, target, outcome });
  }
  public static void Event(CentreDb db, string topic, string type, Guid correlation, string userId, object payload, Guid? eventId = null)
  {
    var payloadNode = JsonSerializer.SerializeToNode(payload, Json)!.AsObject();
    if (type == "audit.event" && Tracing.TraceId is { } traceId) payloadNode["trace_id"] = traceId;
    db.Outbox.Add(new Outbox
    {
      Id = eventId ?? Guid.NewGuid(),
      Traceparent = Tracing.TraceId is null ? null : System.Diagnostics.Activity.Current!.Id,
      Tracestate = Tracing.TraceId is null ? null : System.Diagnostics.Activity.Current!.TraceStateString,
      Topic = topic,
      Key = correlation.ToString(),
      Envelope = Encode(new { event_id = eventId ?? Guid.NewGuid(), type, version = 1, occurred_at = DateTime.UtcNow.ToString("O", CultureInfo.InvariantCulture), correlation_id = correlation, user_id = userId, producer = "control-centre", payload = payloadNode })
    });
  }
}
