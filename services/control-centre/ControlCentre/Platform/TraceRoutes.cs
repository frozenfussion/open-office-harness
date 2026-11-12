// SPDX-License-Identifier: AGPL-3.0-only
using System.Globalization;
using System.Net;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace ControlCentre.Platform;

public sealed class TraceClient(HttpClient http, IConfiguration config)
{
  public static bool ValidId(string id) => id.Length == 32 && Regex.IsMatch(id, "^[0-9a-f]{32}$") && id.Any(c => c != '0');
  public async Task<JsonObject> Get(string id, CancellationToken ct)
  {
    if (string.IsNullOrWhiteSpace(config["CC_JAEGER_QUERY_URL"])) throw Unavailable();
    using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct); timeout.CancelAfter(TimeSpan.FromSeconds(5));
    try
    {
      using var response = await http.GetAsync(config["CC_JAEGER_QUERY_URL"]!.TrimEnd('/') + "/api/v3/traces/" + id, timeout.Token);
      if (response.StatusCode == HttpStatusCode.NotFound) throw new ApiException(404, "trace_not_found", "This trace has expired");
      if (!response.IsSuccessStatusCode) throw Unavailable();
      var node = await response.Content.ReadFromJsonAsync<JsonObject>(timeout.Token);
      return Parse(id, node!);
    }
    catch (Exception e) when (e is HttpRequestException or OperationCanceledException or JsonException or InvalidOperationException or FormatException or OverflowException or ArgumentException or NullReferenceException or KeyNotFoundException) { throw Unavailable(); }
  }
  private static ApiException Unavailable() => new(503, "tracing_unavailable", "Tracing is unavailable");
  public static JsonObject Parse(string id, JsonObject node)
  {
    var spans = new List<(long Start, JsonObject Span)>();
    if (node["result"]?["resourceSpans"] is not JsonArray resources) throw Unavailable();
    foreach (var resource in resources.OfType<JsonObject>())
    {
      var service = resource["resource"]?["attributes"]?.AsArray().OfType<JsonObject>().FirstOrDefault(x => x["key"]?.GetValue<string>() == "service.name")?["value"]?["stringValue"]?.GetValue<string>() ?? "unknown";
      foreach (var scope in resource["scopeSpans"]?.AsArray().OfType<JsonObject>() ?? [])
        foreach (var span in scope["spans"]?.AsArray().OfType<JsonObject>() ?? [])
        {
          if (span["traceId"]?.GetValue<string>() != id) continue;
          var start = long.Parse(span["startTimeUnixNano"]?.GetValue<string>() ?? "0", CultureInfo.InvariantCulture);
          var end = long.Parse(span["endTimeUnixNano"]?.GetValue<string>() ?? "0", CultureInfo.InvariantCulture);
          var attributes = new JsonObject();
          foreach (var attribute in span["attributes"]?.AsArray().OfType<JsonObject>() ?? [])
          {
            var key = attribute["key"]!.GetValue<string>();
            if (Tracing.Attributes.Contains(key) && attribute["value"] is JsonObject value)
              attributes[key] = (value["stringValue"] ?? value["intValue"] ?? value["doubleValue"] ?? value["boolValue"])?.DeepClone();
          }
          var status = span["status"]?["code"]?.ToString();
          spans.Add((start, new JsonObject
          {
            ["span_id"] = span["spanId"]?.DeepClone(),
            ["parent_span_id"] = span["parentSpanId"]?.DeepClone(),
            ["service"] = service,
            ["name"] = span["name"]?.DeepClone(),
            ["kind"] = span["kind"]?.DeepClone(),
            ["start"] = DateTimeOffset.UnixEpoch.AddTicks(start / 100).ToString("O", CultureInfo.InvariantCulture),
            ["duration_ms"] = Math.Max(0, (end - start) / 1_000_000d),
            ["status"] = status is "STATUS_CODE_ERROR" or "2" ? "error" : "ok",
            ["attributes"] = attributes
          }));
        }
    }
    if (spans.Count == 0) throw new ApiException(404, "trace_not_found", "This trace has expired");
    return new JsonObject { ["trace_id"] = id, ["spans"] = new JsonArray(spans.OrderBy(x => x.Start).ThenBy(x => x.Span["span_id"]!.ToString(), StringComparer.Ordinal).Select(x => (JsonNode)x.Span).ToArray()) };
  }
}
public static class TraceRoutes
{
  public static void Map(WebApplication app) => app.MapGet("/api/admin/traces/{trace_id}", async (string trace_id, HttpContext c, TraceClient client) =>
  {
    Api.Authorize(c); Api.Query(c); Api.Require(TraceClient.ValidId(trace_id), "Invalid trace ID");
    return Results.Ok(await client.Get(trace_id, c.RequestAborted));
  }).RequireAuthorization();
}
