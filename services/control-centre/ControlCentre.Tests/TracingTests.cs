// SPDX-License-Identifier: AGPL-3.0-only
using System.Diagnostics;
using System.Net;
using System.Text.Json.Nodes;
using ControlCentre.Platform;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using OpenTelemetry.Context.Propagation;
using Microsoft.Extensions.DependencyInjection;
using OpenTelemetry;
using OpenTelemetry.Trace;
using Xunit;

namespace ControlCentre.Tests;

public sealed class CapturedSpans : BaseExporter<Activity>
{
  public List<Activity> Spans { get; } = [];
  public override ExportResult Export(in Batch<Activity> batch) { foreach (var span in batch) Spans.Add(span); return ExportResult.Success; }
}
public sealed class TracingTests
{
  [Fact]
  public void EmptyEndpointRegistersNoProviderAndNoAuditTraceId()
  {
    var services = new ServiceCollection();
    foreach (var endpoint in new string?[] { null, "", " " })
    {
      var config = new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?> { ["OTEL_EXPORTER_OTLP_ENDPOINT"] = endpoint }).Build();
      Assert.False(Tracing.Register(services, config)); Assert.Empty(services);
    }
    using var unrecorded = new Activity("synthetic").SetIdFormat(ActivityIdFormat.W3C).Start();
    using var db = new CentreDb(new Microsoft.EntityFrameworkCore.DbContextOptionsBuilder<CentreDb>().UseNpgsql("Host=127.0.0.1;Database=controlcentre_test").Options);
    Api.Event(db, "audit.events", "audit.event", Guid.NewGuid(), "synthetic", new { actor = "synthetic" });
    Assert.Null(JsonNode.Parse(db.Outbox.Local.Single().Envelope)!["payload"]!["trace_id"]);
  }
  [Fact]
  public void ManualSourceIsRegisteredAndFiltersTagsEventsAndStatusDescription()
  {
    var capture = new CapturedSpans();
    using var provider = Tracing.Configure(Sdk.CreateTracerProviderBuilder()).AddProcessor(new SimpleActivityExportProcessor(capture)).Build();
    using (var span = Tracing.Start("audit.events", ActivityKind.Producer))
    {
      Assert.NotNull(span); span.SetTag("url.full", "private-marker"); span.SetTag("ooh.tokens", 4);
      span.AddEvent(new ActivityEvent("exception", tags: new ActivityTagsCollection { ["exception.message"] = "private-marker" }));
      span.SetStatus(ActivityStatusCode.Error, "private-marker");
    }
    var exported = Assert.Single(capture.Spans); Assert.Equal(ActivityStatusCode.Error, exported.Status); Assert.Null(exported.StatusDescription);
    Assert.Empty(exported.Events); Assert.All(exported.TagObjects, tag => Assert.Contains(tag.Key, Tracing.Attributes));
    Assert.DoesNotContain("private-marker", Api.Encode(exported.TagObjects));
  }
  [Fact]
  public void KafkaHeadersContinueTraceAndStateAndAuditOutboxKeepsContext()
  {
    using var provider = Tracing.Configure(Sdk.CreateTracerProviderBuilder()).Build();
    using var root = Tracing.Source.StartActivity("request"); Assert.NotNull(root); root.TraceStateString = "synthetic=value";
    using var db = new CentreDb(new Microsoft.EntityFrameworkCore.DbContextOptionsBuilder<CentreDb>().UseNpgsql("Host=127.0.0.1;Database=controlcentre_test").Options);
    Api.Event(db, "audit.events", "audit.event", Guid.NewGuid(), "synthetic", new { actor = "synthetic" });
    var row = db.Outbox.Local.Single(); Assert.Equal(root.Id, row.Traceparent); Assert.Equal(root.TraceStateString, row.Tracestate);
    Assert.Equal(root.TraceId.ToHexString(), JsonNode.Parse(row.Envelope)!["payload"]!["trace_id"]!.GetValue<string>());
    using var send = Tracing.Start("audit.events", ActivityKind.Producer); var headers = Tracing.Headers();
    using var process = Tracing.Start("audit.events", ActivityKind.Consumer, Tracing.Header(headers, "traceparent"), Tracing.Header(headers, "tracestate"));
    Assert.Equal(root.TraceId, process!.TraceId); Assert.Equal(send!.SpanId, process.ParentSpanId); Assert.Equal(root.TraceStateString, process.TraceStateString);
  }
  [Fact]
  public async Task InternalHttpKeepsParentAndIngressGetsNewTraceAndHealthIsExcluded()
  {
    var capture = new CapturedSpans();
    var previous = DistributedContextPropagator.Current; var previousOtel = Propagators.DefaultTextMapPropagator;
    DistributedContextPropagator.Current = new IngressPropagator(); Sdk.SetDefaultTextMapPropagator(new IngressTextMapPropagator());
    try
    {
      using var provider = Tracing.Configure(Sdk.CreateTracerProviderBuilder()).AddProcessor(new SimpleActivityExportProcessor(capture)).Build();
      using var host = new Host(); using var client = host.Client();
      const string trace = "12345678901234567890123456789012";
      client.DefaultRequestHeaders.Add("traceparent", "00-" + trace + "-1234567890123456-01");
      await client.GetAsync("/api/admin/traces/invalid", TestContext.Current.CancellationToken);
      var internalSpan = capture.Spans.Last(x => x.Kind == ActivityKind.Server); Assert.Equal(trace, internalSpan.TraceId.ToHexString());
      client.DefaultRequestHeaders.Add("X-Forwarded-For", "192.0.2.1");
      await client.GetAsync("/api/admin/traces/invalid", TestContext.Current.CancellationToken);
      var externalSpan = capture.Spans.Last(x => x.Kind == ActivityKind.Server); Assert.NotEqual(trace, externalSpan.TraceId.ToHexString()); Assert.Equal(default, externalSpan.ParentSpanId);
      var count = capture.Spans.Count; await client.GetAsync("/api/admin/health", TestContext.Current.CancellationToken); Assert.Equal(count, capture.Spans.Count);
    }
    finally { DistributedContextPropagator.Current = previous; Sdk.SetDefaultTextMapPropagator(previousOtel); }
  }
  [Fact]
  public async Task UnhandledRouteErrorExportsNoMarkerEventsOrPrivateTags()
  {
    var capture = new CapturedSpans();
    using var provider = Tracing.Configure(Sdk.CreateTracerProviderBuilder()).AddProcessor(new SimpleActivityExportProcessor(capture)).Build();
    Environment.SetEnvironmentVariable("CC_JAEGER_QUERY_URL", "http://tracing.invalid");
    using var host = new Host(); using var client = host.Client();
    host.Gateway.Answer = _ => throw new Exception("private-marker");
    try { await client.GetAsync("/api/admin/traces/12345678901234567890123456789012", TestContext.Current.CancellationToken); }
    finally { Environment.SetEnvironmentVariable("CC_JAEGER_QUERY_URL", null); }
    Assert.All(capture.Spans, span => { Assert.Empty(span.Events); Assert.All(span.TagObjects, tag => Assert.Contains(tag.Key, Tracing.Attributes)); Assert.DoesNotContain("private-marker", span.StatusDescription ?? ""); });
    Assert.Contains(capture.Spans, span => span.Kind == ActivityKind.Server && span.Status == ActivityStatusCode.Error);
  }
  [Fact]
  public void ParsesVersionedJaegerFixtureAndReducesSyntheticOtlpFields()
  {
    var node = JsonNode.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Fixtures/jaeger-2.23-get-trace.json")))!.AsObject();
    const string id = "00000000000000000000000000000001";
    Assert.Equal("error", TraceClient.Parse(id, node)["spans"]![0]!["status"]!.GetValue<string>());
    var resource = node["result"]!["resourceSpans"]![0]!;
    resource["resource"]!["attributes"] = JsonNode.Parse("""[{"key":"service.name","value":{"stringValue":"synthetic-service"}}]""");
    var span = resource["scopeSpans"]![0]!["spans"]![0]!;
    span["startTimeUnixNano"] = "1000000000"; span["endTimeUnixNano"] = "1002000000";
    span["attributes"] = JsonNode.Parse("""[{"key":"ooh.tokens","value":{"intValue":"4"}},{"key":"url.full","value":{"stringValue":"private-marker"}}]""");
    var parsed = TraceClient.Parse(id, node); Assert.DoesNotContain("private-marker", parsed.ToJsonString()); Assert.Equal(2d, parsed["spans"]![0]!["duration_ms"]!.GetValue<double>());
    Assert.Equal("synthetic-service", parsed["spans"]![0]!["service"]!.GetValue<string>());
  }
  [Fact]
  public async Task TraceRouteRequiresAdminAndValidIdAndDistinguishesUnavailableAndExpired()
  {
    Environment.SetEnvironmentVariable("CC_JAEGER_QUERY_URL", "http://tracing.invalid");
    try
    {
      using var host = new Host(); using var anonymous = host.CreateClient(); using var user = host.Client("harness"); using var admin = host.Client();
      const string path = "/api/admin/traces/00000000000000000000000000000001";
      Assert.Equal(HttpStatusCode.Unauthorized, (await anonymous.GetAsync(path, TestContext.Current.CancellationToken)).StatusCode);
      Assert.Equal(HttpStatusCode.Forbidden, (await user.GetAsync(path, TestContext.Current.CancellationToken)).StatusCode);
      foreach (var id in new[] { "bad", new string('0', 32), new string('A', 32) }) Assert.Equal(HttpStatusCode.BadRequest, (await admin.GetAsync("/api/admin/traces/" + id, TestContext.Current.CancellationToken)).StatusCode);
      host.Gateway.Answer = _ => Task.FromResult(new HttpResponseMessage(HttpStatusCode.NotFound));
      var response = await admin.GetAsync(path, TestContext.Current.CancellationToken); Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
      Assert.Contains("trace_not_found", await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken));
      host.Gateway.Answer = _ => throw new HttpRequestException("synthetic");
      response = await admin.GetAsync(path, TestContext.Current.CancellationToken); Assert.Equal(HttpStatusCode.ServiceUnavailable, response.StatusCode);
      Assert.Contains("tracing_unavailable", await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken));
      host.Gateway.Answer = _ => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent("not json") });
      Assert.Equal(HttpStatusCode.ServiceUnavailable, (await admin.GetAsync(path, TestContext.Current.CancellationToken)).StatusCode);
      host.Gateway.Answer = _ => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Fixtures/jaeger-2.23-get-trace.json"))), });
      Assert.Equal(HttpStatusCode.OK, (await admin.GetAsync(path, TestContext.Current.CancellationToken)).StatusCode);
      Assert.Equal("/api/v3/traces/00000000000000000000000000000001", host.Gateway.GatewayUrl);
    }
    finally { Environment.SetEnvironmentVariable("CC_JAEGER_QUERY_URL", null); }
  }
}
