// SPDX-License-Identifier: AGPL-3.0-only
using System.Diagnostics;
using System.Reflection;
using System.Text;
using Confluent.Kafka;
using OpenTelemetry;
using OpenTelemetry.Exporter;
using OpenTelemetry.Resources;
using OpenTelemetry.Context.Propagation;
using OpenTelemetry.Trace;

namespace ControlCentre.Platform;

public static class Tracing
{
  public const string SourceName = "ControlCentre.Kafka";
  public static readonly ActivitySource Source = new(SourceName);
  public static readonly HashSet<string> Attributes = ["ooh.user_id", "ooh.conversation_id", "ooh.job_id", "ooh.correlation_id", "ooh.model_entry_id", "ooh.tier", "ooh.purpose", "ooh.skill", "ooh.status", "ooh.error_code", "ooh.attempt", "ooh.tokens", "ooh.connection_type", "http.request.method", "http.route", "http.response.status_code", "server.port", "messaging.destination.name", "messaging.operation.type"];
  public static bool Register(IServiceCollection services, IConfiguration config)
  {
    if (string.IsNullOrWhiteSpace(config["OTEL_EXPORTER_OTLP_ENDPOINT"])) return false;
    DistributedContextPropagator.Current = new IngressPropagator();
    Sdk.SetDefaultTextMapPropagator(new IngressTextMapPropagator());
    services.AddOpenTelemetry().ConfigureResource(r => r.AddService(config["OTEL_SERVICE_NAME"] ?? "control-centre"))
      .WithTracing(t => Configure(t).AddOtlpExporter(o =>
      {
        o.Endpoint = new Uri(config["OTEL_EXPORTER_OTLP_ENDPOINT"]!.TrimEnd('/') + "/v1/traces");
        o.Protocol = OtlpExportProtocol.HttpProtobuf;
        o.TimeoutMilliseconds = 5000;
        o.ExportProcessorType = ExportProcessorType.Batch;
      }));
    return true;
  }
  public static TracerProviderBuilder Configure(TracerProviderBuilder builder) => builder
    .SetSampler(new ParentBasedSampler(new AlwaysOnSampler())).AddSource(SourceName)
    .AddAspNetCoreInstrumentation(o => { o.RecordException = false; o.Filter = c => c.Request.Path != "/health" && c.Request.Path != "/api/admin/health"; })
    .AddHttpClientInstrumentation(o =>
    {
      o.RecordException = false;
      o.FilterHttpRequestMessage = r => r.RequestUri?.AbsolutePath != "/health" && r.RequestUri?.AbsolutePath.EndsWith("/.well-known/openid-configuration", StringComparison.Ordinal) != true
        && r.Options.TryGetValue(InternalRequest, out var enabled) && enabled;
    }).AddProcessor(new PrivateSpanProcessor());
  public static readonly HttpRequestOptionsKey<bool> InternalRequest = new("ooh.internal");
  public static string? TraceId => Source.HasListeners() && Activity.Current is { IdFormat: ActivityIdFormat.W3C } a && a.TraceId != default ? a.TraceId.ToHexString() : null;
  public static Activity? Start(string topic, ActivityKind kind, string? parent = null, string? state = null)
  {
    Activity? span;
    if (parent is not null)
    {
      ActivityContext.TryParse(parent, state, true, out var context);
      span = Source.StartActivity((kind == ActivityKind.Producer ? "send " : "process ") + topic, kind, context);
    }
    else span = Source.StartActivity((kind == ActivityKind.Producer ? "send " : "process ") + topic, kind);
    span?.SetTag("messaging.destination.name", topic);
    span?.SetTag("messaging.operation.type", kind == ActivityKind.Producer ? "send" : "process");
    return span;
  }
  public static Headers Headers()
  {
    var headers = new Headers();
    if (TraceId is not null)
    {
      headers.Add("traceparent", Encoding.UTF8.GetBytes(Activity.Current!.Id!));
      if (Activity.Current.TraceStateString is { Length: > 0 } state) headers.Add("tracestate", Encoding.UTF8.GetBytes(state));
    }
    return headers;
  }
  public static string? Header(Headers? headers, string key) => headers?.TryGetLastBytes(key, out var bytes) == true ? Encoding.UTF8.GetString(bytes) : null;
}

public sealed class PrivateSpanProcessor : BaseProcessor<Activity>
{
  // Activity has no public event removal API in .NET 10; clear its runtime event list before the batch exporter sees it.
  private static readonly FieldInfo Events = typeof(Activity).GetField("_events", BindingFlags.Instance | BindingFlags.NonPublic)!;
  public override void OnEnd(Activity activity)
  {
    foreach (var tag in activity.TagObjects.ToArray()) if (!Tracing.Attributes.Contains(tag.Key)) activity.SetTag(tag.Key, null);
    Events.SetValue(activity, null);
    activity.SetStatus(activity.Status, activity.GetTagItem("ooh.error_code") as string);
  }
}

public sealed class IngressPropagator : DistributedContextPropagator
{
  private readonly DistributedContextPropagator inner = CreateDefaultPropagator();
  public override IReadOnlyCollection<string> Fields => inner.Fields;
  public override void Inject(Activity? activity, object? carrier, PropagatorSetterCallback? setter) => inner.Inject(activity, carrier, setter);
  public override void ExtractTraceIdAndState(object? carrier, PropagatorGetterCallback? getter, out string? traceId, out string? traceState)
  {
    string? forwarded = null; IEnumerable<string>? values = null;
    getter?.Invoke(carrier, "X-Forwarded-For", out forwarded, out values);
    if (forwarded is not null || values is not null) { traceId = null; traceState = null; return; }
    inner.ExtractTraceIdAndState(carrier, getter, out traceId, out traceState);
  }
  public override IEnumerable<KeyValuePair<string, string?>>? ExtractBaggage(object? carrier, PropagatorGetterCallback? getter) => null;
}

public sealed class IngressTextMapPropagator : TextMapPropagator
{
  private readonly TraceContextPropagator inner = new();
  public override ISet<string> Fields => inner.Fields;
  public override void Inject<T>(PropagationContext context, T carrier, Action<T, string, string> setter) => inner.Inject(context, carrier, setter);
  public override PropagationContext Extract<T>(PropagationContext context, T carrier, Func<T, string, IEnumerable<string>?> getter) =>
    carrier is HttpRequest request && request.Headers.ContainsKey("X-Forwarded-For") ? default : inner.Extract(context, carrier, getter);
}
