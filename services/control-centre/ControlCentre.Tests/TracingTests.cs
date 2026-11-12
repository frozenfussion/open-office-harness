// SPDX-License-Identifier: AGPL-3.0-only
using System.Diagnostics;
using System.Net;
using System.Text.Json.Nodes;
using ControlCentre.Platform;
using Microsoft.EntityFrameworkCore;
using Microsoft.AspNetCore.Hosting;
using Microsoft.Extensions.Configuration;
using OpenTelemetry.Context.Propagation;
using Microsoft.Extensions.DependencyInjection;
using OpenTelemetry;
using OpenTelemetry.Trace;
using Xunit;

namespace ControlCentre.Tests;

public sealed class CapturedSpans : BaseExporter<Activity>
{
  private readonly System.Collections.Concurrent.ConcurrentQueue<Activity> spans = new();
  public List<Activity> Spans => spans.ToList();
  public override ExportResult Export(in Batch<Activity> batch) { foreach (var span in batch) spans.Enqueue(span); return ExportResult.Success; }
  public async Task<Activity> WaitForServerSpan(int after = 0)
  {
    using var timeout = CancellationTokenSource.CreateLinkedTokenSource(TestContext.Current.CancellationToken);
    timeout.CancelAfter(TimeSpan.FromSeconds(5));
    while (true)
    {
      var span = Spans.Skip(after).FirstOrDefault(x => x.Kind == ActivityKind.Server);
      if (span is not null) return span;
      await Task.Delay(10, timeout.Token);
    }
  }
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
    var capture = new CapturedExports();
    using var provider = Tracing.Configure(Sdk.CreateTracerProviderBuilder()).AddProcessor(new SimpleActivityExportProcessor(new PrivateSpanExporter(capture))).Build();
    using (var span = Tracing.Start("audit.events", ActivityKind.Producer))
    {
      Assert.NotNull(span); span.SetTag("url.full", "private-marker"); span.SetTag("ooh.tokens", 4);
      span.AddEvent(new ActivityEvent("exception", tags: new ActivityTagsCollection { ["exception.message"] = "private-marker" }));
      span.SetStatus(ActivityStatusCode.Error, "private-marker");
      Assert.Null(Record.Exception(() => new PrivateSpanProcessor().OnEnd(span)));
      Assert.Empty(span.Events);
    }
    var exported = Assert.Single(capture.Spans); Assert.Equal(ActivityStatusCode.Error, exported.Status); Assert.Null(exported.ErrorCode);
    Assert.All(exported.Attributes, tag => Assert.Contains(tag.Key, Tracing.Attributes));
    using var batch = new Batch<ExportedSpan>(exported);
    var bytes = OtlpHttpSpanExporter.Encode(batch, "control-centre");
    Assert.DoesNotContain("private-marker", System.Text.Encoding.UTF8.GetString(bytes));
    Assert.DoesNotContain(OtlpFields.Spans(bytes).Single(), field => field.Number == 11);
  }
  [Theory]
  [InlineData("always_off", false)]
  [InlineData("always_on", true)]
  [InlineData("parentbased_always_on", true)]
  public void SamplerFollowsEnvironment(string sampler, bool recorded)
  {
    var previous = Environment.GetEnvironmentVariable("OTEL_TRACES_SAMPLER");
    try
    {
      Environment.SetEnvironmentVariable("OTEL_TRACES_SAMPLER", sampler);
      var capture = new CapturedSpans();
      using var provider = Tracing.Configure(Sdk.CreateTracerProviderBuilder()).AddProcessor(new SimpleActivityExportProcessor(capture)).Build();
      using (var span = Tracing.Source.StartActivity("synthetic")) Assert.Equal(recorded, span?.Recorded == true);
      Assert.Equal(recorded ? 1 : 0, capture.Spans.Count);
    }
    finally { Environment.SetEnvironmentVariable("OTEL_TRACES_SAMPLER", previous); }
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
    var endpoint = Environment.GetEnvironmentVariable("OTEL_EXPORTER_OTLP_ENDPOINT");
    Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:1");
    try
    {
      using var host = new Host();
      using var realHost = host.WithWebHostBuilder(builder => builder.ConfigureServices(services =>
        services.AddOpenTelemetry().WithTracing(t => t.AddProcessor(new SimpleActivityExportProcessor(capture)))));
      using var client = realHost.CreateClient();
      const string trace = "12345678901234567890123456789012";
      client.DefaultRequestHeaders.Add("traceparent", "00-" + trace + "-1234567890123456-01");
      client.DefaultRequestHeaders.Add("tracestate", "synthetic=outside");
      client.DefaultRequestHeaders.Add("baggage", "marker=outside");
      await client.GetAsync("/api/admin/traces/invalid", TestContext.Current.CancellationToken);
      var internalSpan = await capture.WaitForServerSpan(); Assert.Equal(trace, internalSpan.TraceId.ToHexString());
      Assert.Equal("1234567890123456", internalSpan.ParentSpanId.ToHexString()); Assert.Equal("synthetic=outside", internalSpan.TraceStateString);
      var prior = capture.Spans.Count;
      client.DefaultRequestHeaders.Add("X-Forwarded-For", "192.0.2.1");
      await client.GetAsync("/api/admin/traces/invalid", TestContext.Current.CancellationToken);
      var externalSpan = await capture.WaitForServerSpan(prior); Assert.NotEqual(trace, externalSpan.TraceId.ToHexString()); Assert.Equal(default, externalSpan.ParentSpanId);
      Assert.Null(externalSpan.TraceStateString); Assert.Empty(externalSpan.Baggage);
      prior = capture.Spans.Count;
      await client.GetAsync("/api/admin/traces/invalid", TestContext.Current.CancellationToken);
      var nextExternal = await capture.WaitForServerSpan(prior);
      Assert.NotEqual(externalSpan.TraceId, nextExternal.TraceId); Assert.NotEqual(trace, nextExternal.TraceId.ToHexString());
      Assert.Equal(default, nextExternal.ParentSpanId); Assert.Null(nextExternal.TraceStateString); Assert.Empty(nextExternal.Baggage);
      var count = capture.Spans.Count; await client.GetAsync("/api/admin/health", TestContext.Current.CancellationToken); Assert.Equal(count, capture.Spans.Count);
    }
    finally { Environment.SetEnvironmentVariable("OTEL_EXPORTER_OTLP_ENDPOINT", endpoint); DistributedContextPropagator.Current = previous; Sdk.SetDefaultTextMapPropagator(previousOtel); }
  }
  [Fact]
  public async Task UnhandledRouteErrorExportsNoMarkerEventsOrPrivateTags()
  {
    var capture = new CapturedSpans(); var filtered = new CapturedExports();
    using var provider = Tracing.Configure(Sdk.CreateTracerProviderBuilder())
      .AddProcessor(new SimpleActivityExportProcessor(new PrivateSpanExporter(filtered)))
      .AddProcessor(new SimpleActivityExportProcessor(capture)).Build();
    var previous = Environment.GetEnvironmentVariable("CC_JAEGER_QUERY_URL");
    Environment.SetEnvironmentVariable("CC_JAEGER_QUERY_URL", "http://127.0.0.1:1");
    try
    {
      using var host = new Host();
      host.Gateway.Answer = _ => throw new Exception("private-marker");
      using var client = host.Client();
      var response = await client.GetAsync("/api/admin/traces/12345678901234567890123456789012", TestContext.Current.CancellationToken);
      Assert.Equal(HttpStatusCode.ServiceUnavailable, response.StatusCode);
      Assert.Equal(1, host.Gateway.GatewayCalls);
      var server = await capture.WaitForServerSpan();
      Assert.Equal(ActivityStatusCode.Error, server.Status);
      Assert.All(filtered.Spans, span => { Assert.All(span.Attributes, tag => Assert.Contains(tag.Key, Tracing.Attributes)); Assert.DoesNotContain("private-marker", span.ErrorCode ?? ""); });
      var exported = Assert.Single(filtered.Spans, x => x.Kind == ActivityKind.Server);
      using var batch = new Batch<ExportedSpan>(exported);
      var bytes = OtlpHttpSpanExporter.Encode(batch, "control-centre");
      Assert.DoesNotContain("private-marker", System.Text.Encoding.UTF8.GetString(bytes));
      Assert.DoesNotContain(OtlpFields.Spans(bytes).Single(), field => field.Number == 11);
    }
    finally { Environment.SetEnvironmentVariable("CC_JAEGER_QUERY_URL", previous); }
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
