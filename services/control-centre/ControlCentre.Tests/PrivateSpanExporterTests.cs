// SPDX-License-Identifier: AGPL-3.0-only
using System.Buffers.Binary;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.Net;
using System.Text;
using ControlCentre.Platform;
using OpenTelemetry;
using OpenTelemetry.Trace;
using Xunit;

namespace ControlCentre.Tests;

public sealed class CapturedExports : BaseExporter<ExportedSpan>
{
  private readonly ConcurrentQueue<ExportedSpan> spans = new();
  public ExportedSpan[] Spans => spans.ToArray();
  public override ExportResult Export(in Batch<ExportedSpan> batch) { foreach (var span in batch) spans.Enqueue(span); return ExportResult.Success; }
}
public static class OtlpFields
{
  public sealed record Field(int Number, byte[] Bytes, ulong Value);
  public static List<Field> Read(byte[] bytes)
  {
    var fields = new List<Field>(); var offset = 0;
    ulong Varint()
    {
      ulong value = 0; var shift = 0;
      while (true) { var part = bytes[offset++]; value |= (ulong)(part & 127) << shift; if (part < 128) return value; shift += 7; }
    }
    while (offset < bytes.Length)
    {
      var tag = Varint(); var number = (int)(tag >> 3);
      switch (tag & 7)
      {
        case 0: fields.Add(new(number, [], Varint())); break;
        case 1: fields.Add(new(number, [], BinaryPrimitives.ReadUInt64LittleEndian(bytes.AsSpan(offset, 8)))); offset += 8; break;
        case 2: var size = checked((int)Varint()); fields.Add(new(number, bytes.AsSpan(offset, size).ToArray(), 0)); offset += size; break;
        case 5: fields.Add(new(number, [], BinaryPrimitives.ReadUInt32LittleEndian(bytes.AsSpan(offset, 4)))); offset += 4; break;
        default: throw new InvalidOperationException("Unexpected protobuf field");
      }
    }
    return fields;
  }
  public static List<List<Field>> Spans(byte[] request) => Read(request).Where(x => x.Number == 1)
    .SelectMany(resource => Read(resource.Bytes).Where(x => x.Number == 2))
    .SelectMany(scope => Read(scope.Bytes).Where(x => x.Number == 2)).Select(span => Read(span.Bytes)).ToList();
}
public sealed class PrivateSpanExporterTests
{
  private sealed class Transport : HttpMessageHandler
  {
    public byte[]? Body { get; private set; }
    public string? ContentType { get; private set; }
    public Uri? Address { get; private set; }
    public Exception? Failure { get; init; }
    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
    {
      if (Failure is not null) throw Failure;
      Body = await request.Content!.ReadAsByteArrayAsync(ct); ContentType = request.Content.Headers.ContentType!.MediaType; Address = request.RequestUri;
      return new(HttpStatusCode.OK);
    }
  }
  [Fact]
  public void WrapperExportsEventFreeProtobufWithOriginalIdentityParentTimesTypesAndService()
  {
    using var transport = new Transport();
    var endpoint = new Uri("http://127.0.0.1:1/v1/traces");
    var sink = new OtlpHttpSpanExporter(new OtlpHttpSettings(endpoint, "http/protobuf", 5000), "control-centre", new HttpClient(transport));
    using var provider = Tracing.Configure(Sdk.CreateTracerProviderBuilder()).AddProcessor(new SimpleActivityExportProcessor(new PrivateSpanExporter(sink))).Build();
    using var parent = Tracing.Source.StartActivity("synthetic parent"); Assert.NotNull(parent);
    string id; string trace; DateTime start; TimeSpan duration;
    using (var span = Tracing.Start("audit.events", ActivityKind.Producer))
    {
      Assert.NotNull(span); id = span.SpanId.ToHexString(); trace = span.TraceId.ToHexString(); start = span.StartTimeUtc;
      span.SetTag("ooh.tokens", 17); span.SetTag("ooh.tier", -1); span.SetTag("ooh.status", true); span.SetTag("ooh.attempt", 1.25);
      span.SetTag("ooh.error_code", "synthetic_error"); span.SetTag("url.full", "private-marker");
      span.SetStatus(ActivityStatusCode.Error, "private-marker"); span.AddEvent(new ActivityEvent("exception", tags: new ActivityTagsCollection { ["message"] = "private-marker" }));
      Assert.Null(Record.Exception(() => new PrivateSpanProcessor().OnEnd(span)));
      span.Stop(); duration = span.Duration;
    }
    Assert.Equal(endpoint, transport.Address); Assert.Equal("application/x-protobuf", transport.ContentType);
    var body = transport.Body!; Assert.DoesNotContain("private-marker", Encoding.UTF8.GetString(body));
    var fields = Assert.Single(OtlpFields.Spans(body));
    Assert.Equal(trace, Convert.ToHexStringLower(fields.Single(x => x.Number == 1).Bytes));
    Assert.Equal(id, Convert.ToHexStringLower(fields.Single(x => x.Number == 2).Bytes));
    Assert.Equal(parent.SpanId.ToHexString(), Convert.ToHexStringLower(fields.Single(x => x.Number == 4).Bytes));
    var nanos = (ulong)(start.Ticks - DateTime.UnixEpoch.Ticks) * 100;
    Assert.Equal(nanos, fields.Single(x => x.Number == 7).Value); Assert.Equal(nanos + (ulong)duration.Ticks * 100, fields.Single(x => x.Number == 8).Value);
    Assert.Equal(4UL, fields.Single(x => x.Number == 6).Value); Assert.DoesNotContain(fields, x => x.Number is 11 or 13);
    var attributes = fields.Where(x => x.Number == 9).Select(x => OtlpFields.Read(x.Bytes)).ToDictionary(x => Encoding.UTF8.GetString(x.Single(f => f.Number == 1).Bytes), x => OtlpFields.Read(x.Single(f => f.Number == 2).Bytes));
    Assert.All(attributes.Keys, key => Assert.Contains(key, Tracing.Attributes));
    Assert.Equal(17UL, attributes["ooh.tokens"].Single().Value); Assert.Equal(ulong.MaxValue, attributes["ooh.tier"].Single().Value);
    Assert.Equal(1UL, attributes["ooh.status"].Single().Value); Assert.Equal(1.25, BitConverter.Int64BitsToDouble((long)attributes["ooh.attempt"].Single().Value));
    var status = OtlpFields.Read(fields.Single(x => x.Number == 15).Bytes); Assert.Equal(2UL, status.Single(x => x.Number == 3).Value);
    Assert.Equal("synthetic_error", Encoding.UTF8.GetString(status.Single(x => x.Number == 2).Bytes));
    var resource = OtlpFields.Read(OtlpFields.Read(body).Single().Bytes).Single(x => x.Number == 1);
    var service = OtlpFields.Read(OtlpFields.Read(resource.Bytes).Single().Bytes);
    Assert.Equal("service.name", Encoding.UTF8.GetString(service.Single(x => x.Number == 1).Bytes));
    Assert.Equal("control-centre", Encoding.UTF8.GetString(OtlpFields.Read(service.Single(x => x.Number == 2).Bytes).Single().Bytes));
  }
  [Fact]
  public void ExportFailureDoesNotThrowFromActivityStop()
  {
    using var transport = new Transport { Failure = new HttpRequestException("private-marker") };
    var sink = new OtlpHttpSpanExporter(new OtlpHttpSettings(new Uri("http://127.0.0.1:1/v1/traces"), "http/protobuf", 5000), "control-centre", new HttpClient(transport));
    using var provider = Tracing.Configure(Sdk.CreateTracerProviderBuilder()).AddProcessor(new SimpleActivityExportProcessor(new PrivateSpanExporter(sink))).Build();
    using var span = Tracing.Source.StartActivity("synthetic"); Assert.NotNull(span); Assert.Null(Record.Exception(span.Stop));
  }
}
