// SPDX-License-Identifier: AGPL-3.0-only
using System.Buffers.Binary;
using System.Diagnostics;
using System.Net.Http.Headers;
using System.Text;
using OpenTelemetry;

namespace ControlCentre.Platform;

// The projection has no events, baggage or links, and retains the original span identities.
public sealed record ExportedSpan(string TraceId, string SpanId, string? ParentSpanId, string? TraceState,
  string Scope, string? ScopeVersion, string Name, ActivityKind Kind, DateTime Start, TimeSpan Duration,
  ActivityTraceFlags Flags, ActivityStatusCode Status, string? ErrorCode, KeyValuePair<string, object?>[] Attributes);

public sealed class PrivateSpanExporter(BaseExporter<ExportedSpan> inner) : BaseExporter<Activity>
{
  public override ExportResult Export(in Batch<Activity> batch)
  {
    try
    {
      var spans = new List<ExportedSpan>();
      foreach (var activity in batch)
        spans.Add(new(activity.TraceId.ToHexString(), activity.SpanId.ToHexString(), activity.ParentSpanId == default ? null : activity.ParentSpanId.ToHexString(),
          activity.TraceStateString, activity.Source.Name, activity.Source.Version, activity.DisplayName, activity.Kind,
          activity.StartTimeUtc, activity.Duration, activity.ActivityTraceFlags, activity.Status, activity.GetTagItem("ooh.error_code") as string,
          activity.TagObjects.Where(x => Tracing.Attributes.Contains(x.Key)).ToArray()));
      using var filtered = new Batch<ExportedSpan>(spans.ToArray(), spans.Count);
      return inner.Export(filtered);
    }
    catch { return ExportResult.Failure; }
  }
  protected override bool OnForceFlush(int timeoutMilliseconds) => inner.ForceFlush(timeoutMilliseconds);
  protected override bool OnShutdown(int timeoutMilliseconds) => inner.Shutdown(timeoutMilliseconds);
  protected override void Dispose(bool disposing) { if (disposing) inner.Dispose(); }
}

public sealed record OtlpHttpSettings(Uri Endpoint, string Protocol, int TimeoutMilliseconds);

public sealed class OtlpHttpSpanExporter : BaseExporter<ExportedSpan>
{
  private readonly OtlpHttpSettings options;
  private readonly string service;
  private readonly HttpClient http;
  public OtlpHttpSpanExporter(OtlpHttpSettings options, string service, HttpClient? http = null, ILogger<OtlpHttpSpanExporter>? logger = null)
  {
    if (options.Protocol != "http/protobuf")
      logger?.LogWarning("Unsupported OTEL_EXPORTER_OTLP_PROTOCOL; using http/protobuf");
    this.options = options with { Protocol = "http/protobuf" }; this.service = service; this.http = http ?? new HttpClient();
  }
  public override ExportResult Export(in Batch<ExportedSpan> batch)
  {
    using var suppression = SuppressInstrumentationScope.Begin();
    try
    {
      if (options.Protocol != "http/protobuf") return ExportResult.Failure;
      using var timeout = new CancellationTokenSource(options.TimeoutMilliseconds);
      using var request = new HttpRequestMessage(HttpMethod.Post, options.Endpoint) { Content = new ByteArrayContent(Encode(batch, service)) };
      request.Content.Headers.ContentType = new MediaTypeHeaderValue("application/x-protobuf");
      using var response = http.SendAsync(request, timeout.Token).GetAwaiter().GetResult();
      return response.IsSuccessStatusCode ? ExportResult.Success : ExportResult.Failure;
    }
    catch { return ExportResult.Failure; }
  }
  protected override void Dispose(bool disposing) { if (disposing) http.Dispose(); }
  public static byte[] Encode(in Batch<ExportedSpan> batch, string service)
  {
    var resourceSpans = new Proto();
    resourceSpans.Message(1, resource => resource.Message(1, attribute => Attribute(attribute, "service.name", service)));
    foreach (var span in batch)
      resourceSpans.Message(2, scopeSpans =>
      {
        scopeSpans.Message(1, scope => { scope.Text(1, span.Scope); if (span.ScopeVersion is not null) scope.Text(2, span.ScopeVersion); });
        scopeSpans.Message(2, value =>
        {
          value.Bytes(1, Convert.FromHexString(span.TraceId)); value.Bytes(2, Convert.FromHexString(span.SpanId));
          if (span.TraceState is not null) value.Text(3, span.TraceState);
          if (span.ParentSpanId is not null) value.Bytes(4, Convert.FromHexString(span.ParentSpanId));
          value.Text(5, span.Name); value.Integer(6, (ulong)span.Kind + 1);
          var start = checked((ulong)(span.Start.Ticks - DateTime.UnixEpoch.Ticks) * 100);
          value.Fixed64(7, start); value.Fixed64(8, checked(start + (ulong)span.Duration.Ticks * 100));
          foreach (var attribute in span.Attributes) value.Message(9, field => Attribute(field, attribute.Key, attribute.Value));
          value.Message(15, status =>
          {
            if (span.Status == ActivityStatusCode.Error && span.ErrorCode is not null) status.Text(2, span.ErrorCode);
            status.Integer(3, span.Status switch { ActivityStatusCode.Ok => 1UL, ActivityStatusCode.Error => 2UL, _ => 0UL });
          });
          value.Fixed32(16, (uint)span.Flags);
        });
      });
    var request = new Proto(); request.Bytes(1, resourceSpans.ToArray()); return request.ToArray();
  }
  private static void Attribute(Proto field, string key, object? value)
  {
    field.Text(1, key);
    field.Message(2, any =>
    {
      switch (value)
      {
        case string text: any.Text(1, text); break;
        case bool boolean: any.Integer(2, boolean ? 1UL : 0UL); break;
        case byte or sbyte or short or ushort or int or uint or long:
          any.Integer(3, unchecked((ulong)Convert.ToInt64(value, System.Globalization.CultureInfo.InvariantCulture))); break;
        case float or double:
          any.Fixed64(4, unchecked((ulong)BitConverter.DoubleToInt64Bits(Convert.ToDouble(value, System.Globalization.CultureInfo.InvariantCulture)))); break;
      }
    });
  }
  // OTLP trace.proto/common.proto fields; no Span.events (11) field is ever encoded.
  private sealed class Proto
  {
    private readonly MemoryStream bytes = new();
    private void Varint(ulong value)
    {
      while (value >= 128) { bytes.WriteByte((byte)(value | 128)); value >>= 7; }
      bytes.WriteByte((byte)value);
    }
    public void Integer(int field, ulong value) { Varint((ulong)field << 3); Varint(value); }
    public void Fixed64(int field, ulong value)
    { Varint(((ulong)field << 3) | 1); Span<byte> data = stackalloc byte[8]; BinaryPrimitives.WriteUInt64LittleEndian(data, value); bytes.Write(data); }
    public void Fixed32(int field, uint value)
    { Varint(((ulong)field << 3) | 5); Span<byte> data = stackalloc byte[4]; BinaryPrimitives.WriteUInt32LittleEndian(data, value); bytes.Write(data); }
    public void Text(int field, string value) => Bytes(field, Encoding.UTF8.GetBytes(value));
    public void Bytes(int field, byte[] value) { Varint(((ulong)field << 3) | 2); Varint((ulong)value.Length); bytes.Write(value); }
    public void Message(int field, Action<Proto> write) { var child = new Proto(); write(child); Bytes(field, child.ToArray()); }
    public byte[] ToArray() => bytes.ToArray();
  }
}
