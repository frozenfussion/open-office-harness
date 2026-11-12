// SPDX-License-Identifier: AGPL-3.0-only
using System.Diagnostics;
using System.Data.Common;
using Microsoft.EntityFrameworkCore.Diagnostics;
using System.Net;
using System.Net.Http.Json;
using System.Text.Json.Nodes;
using Confluent.Kafka;
using ControlCentre.Platform;
using Microsoft.EntityFrameworkCore;
using OpenTelemetry;
using OpenTelemetry.Trace;
using Xunit;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Builder;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;

namespace ControlCentre.Tests;

public sealed class ReplayTests
{
  private static CentreDb Database(bool owner = false) => new(new DbContextOptionsBuilder<CentreDb>().UseNpgsql(DatabaseConnections.Configure(TestSettings.Load()[owner ? "CC_TEST_DB_MIGRATE_CONNECTION" : "CC_TEST_DB_CONNECTION"])).Options);
  private static async Task Migrate() { await using var db = Database(true); await db.Database.MigrateAsync(TestContext.Current.CancellationToken); }
  private static string Envelope() => Api.Encode(new { event_id = Guid.NewGuid(), type = "approval.requested", version = 1, occurred_at = DateTime.UtcNow.ToString("O"), correlation_id = Guid.NewGuid(), user_id = "synthetic-replay", producer = "synthetic", payload = new { action = "synthetic", details = new { }, risk = "low", requested_by = "worker" } });
  private static DeadLetter Letter(string? original = null, string topic = "dlq.approvals.requested") => new() { Topic = topic, Offset = DateTimeOffset.UtcNow.Ticks, ErrorCode = "processing_failed", ErrorMessage = "Synthetic failure", OriginalMessage = original ?? Envelope() };
  private sealed class DisconnectAfterSend(CancellationTokenSource disconnected) : IKafka
  {
    public bool Sent { get; private set; }
    public Task Publish(string topic, string key, string value, CancellationToken ct)
    {
      ct.ThrowIfCancellationRequested(); Sent = true; disconnected.Cancel(); return Task.CompletedTask;
    }
    public KafkaRecord? Read(CancellationToken ct) => null;
    public void Commit(KafkaRecord record) { }
    public bool Healthy() => true;
  }
  private sealed class DisconnectToken(CancellationToken token) : IStartupFilter
  {
    public Action<IApplicationBuilder> Configure(Action<IApplicationBuilder> next) => app =>
    {
      app.Use(async (context, handler) => { context.RequestAborted = token; await handler(context); }); next(app);
    };
  }
  [DatabaseFact]
  public async Task DisconnectAfterDeliveryStillWritesReplayAndAudit()
  {
    await Migrate(); await using var db = Database(); var row = Letter(); db.DeadLetters.Add(row);
    await db.SaveChangesAsync(TestContext.Current.CancellationToken);
    using var disconnected = new CancellationTokenSource(); var kafka = new DisconnectAfterSend(disconnected);
    using var host = new Host(true);
    using var realHost = host.WithWebHostBuilder(builder => builder.ConfigureServices(services =>
    {
      services.RemoveAll<IKafka>(); services.AddSingleton<IKafka>(kafka);
      services.AddSingleton<IStartupFilter>(new DisconnectToken(disconnected.Token));
    }));
    using var admin = realHost.CreateClient(); using var authenticated = host.Client();
    admin.DefaultRequestHeaders.Authorization = authenticated.DefaultRequestHeaders.Authorization;
    try { await admin.PostAsJsonAsync($"/api/admin/dead-letters/{row.Id}/replay", new { }, TestContext.Current.CancellationToken); }
    catch (OperationCanceledException) when (disconnected.IsCancellationRequested) { }
    Assert.True(kafka.Sent); Assert.True(disconnected.IsCancellationRequested);
    var replay = Assert.Single(await db.DeadLetterReplays.Where(x => x.DeadLetterId == row.Id).ToListAsync(TestContext.Current.CancellationToken));
    Assert.Equal("sent", replay.Outcome);
    var audits = await db.Outbox.Where(x => x.Topic == "audit.events").ToListAsync(TestContext.Current.CancellationToken);
    Assert.Single(audits, x => x.Envelope.Contains("dead_letter.replayed") && x.Envelope.Contains(row.Id.ToString()));
    var audit = Assert.Single(await db.Audit.Where(x => x.Action == "dead_letter.replayed" && x.Target == row.Id.ToString()).ToListAsync(TestContext.Current.CancellationToken));
    Assert.Contains(replay.Id.ToString(), audit.Detail);
  }
  [DatabaseFact]
  public async Task ReplayConfirmsDeliveryKeepsOriginalAndRecordsHistoryAuditAndFailure()
  {
    await Migrate(); await using var db = Database(); var row = Letter(); db.DeadLetters.Add(row); await db.SaveChangesAsync(TestContext.Current.CancellationToken);
    using var provider = Tracing.Configure(Sdk.CreateTracerProviderBuilder()).Build();
    using var host = new Host(true); using var admin = host.Client(); using var user = host.Client("harness"); using var anonymous = host.CreateClient();
    var path = $"/api/admin/dead-letters/{row.Id}/replay";
    Assert.Equal(HttpStatusCode.Unauthorized, (await anonymous.PostAsJsonAsync(path, new { }, TestContext.Current.CancellationToken)).StatusCode);
    Assert.Equal(HttpStatusCode.Forbidden, (await user.PostAsJsonAsync(path, new { }, TestContext.Current.CancellationToken)).StatusCode);
    Assert.Equal(HttpStatusCode.BadRequest, (await admin.PostAsJsonAsync(path + "?extra=1", new { }, TestContext.Current.CancellationToken)).StatusCode);
    Assert.Equal(HttpStatusCode.BadRequest, (await admin.PostAsJsonAsync("/api/admin/dead-letters/bad/replay", new { }, TestContext.Current.CancellationToken)).StatusCode);
    Assert.Equal(HttpStatusCode.NotFound, (await admin.PostAsJsonAsync($"/api/admin/dead-letters/{Guid.NewGuid()}/replay", new { }, TestContext.Current.CancellationToken)).StatusCode);
    var response = await admin.PostAsJsonAsync(path, new { }, TestContext.Current.CancellationToken); Assert.Equal(HttpStatusCode.Accepted, response.StatusCode);
    var result = await response.Content.ReadFromJsonAsync<JsonObject>(TestContext.Current.CancellationToken); Assert.Equal("sent", result!["outcome"]!.GetValue<string>());
    var message = Assert.Single(host.Kafka.Published); Assert.Equal("approvals.requested", message.Topic); Assert.Equal(row.OriginalMessage, message.Value);
    Assert.Equal(JsonNode.Parse(row.OriginalMessage)!["correlation_id"]!.GetValue<string>(), message.Key);
    var audit = (await db.Outbox.Where(x => x.Topic == "audit.events").ToListAsync(TestContext.Current.CancellationToken)).Single(x => x.Envelope.Contains("dead_letter.replayed") && x.Envelope.Contains(row.Id.ToString()));
    Assert.NotNull(audit.Traceparent); var traceId = JsonNode.Parse(audit.Envelope)!["payload"]!["trace_id"]!.GetValue<string>();
    Assert.Contains(traceId, Tracing.Header(host.Kafka.Headers[0], "traceparent")!);
    Assert.Contains(traceId, audit.Traceparent!); Assert.DoesNotContain(row.OriginalMessage, audit.Envelope);
    host.Kafka.Fail = true; response = await admin.PostAsJsonAsync(path, new { }, TestContext.Current.CancellationToken); Assert.Equal(HttpStatusCode.ServiceUnavailable, response.StatusCode);
    Assert.Equal("kafka_unavailable", (await response.Content.ReadFromJsonAsync<JsonObject>(TestContext.Current.CancellationToken))!["code"]!.GetValue<string>());
    var replays = await db.DeadLetterReplays.Where(x => x.DeadLetterId == row.Id).ToListAsync(TestContext.Current.CancellationToken); Assert.Equal(2, replays.Count); Assert.Contains(replays, x => x.Outcome == "failed" && x.ErrorCode == "kafka_unavailable");
    var rows = await admin.GetFromJsonAsync<JsonArray>("/api/admin/dead-letters?topic=" + row.Topic + "&limit=200", TestContext.Current.CancellationToken);
    var view = rows!.Single(x => x!["id"]!.GetValue<string>() == row.Id.ToString())!; Assert.Equal(2, view["replay_count"]!.GetValue<int>()); Assert.True(view["replayable"]!.GetValue<bool>()); Assert.Equal(2, view["replay_history"]!.AsArray().Count); Assert.NotNull(view["last_replayed_at"]);
  }
  [DatabaseFact]
  public async Task ChatAndNonJsonCannotBeReplayed()
  {
    await Migrate(); await using var db = Database(); var rows = new[] { Letter("not json"), Letter("{}"), Letter("[]"), Letter(Envelope(), "dlq.chat.messages") }; db.DeadLetters.AddRange(rows); await db.SaveChangesAsync(TestContext.Current.CancellationToken);
    using var host = new Host(true); using var admin = host.Client();
    foreach (var row in rows)
    {
      var response = await admin.PostAsJsonAsync($"/api/admin/dead-letters/{row.Id}/replay", new { }, TestContext.Current.CancellationToken); Assert.Equal(HttpStatusCode.Conflict, response.StatusCode);
      Assert.Equal("not_replayable", (await response.Content.ReadFromJsonAsync<JsonObject>(TestContext.Current.CancellationToken))!["code"]!.GetValue<string>());
      Assert.False(ReplayRoutes.Replayable(row)); Assert.False(await db.DeadLetterReplays.AnyAsync(x => x.DeadLetterId == row.Id));
    }
    Assert.Empty(host.Kafka.Published);
  }
  [DatabaseFact]
  public async Task ExhaustedApprovalCanBeReplayedAndCreatesApproval()
  {
    await Migrate(); var fault = new ReviewRegressionTests.InsertFailure(3);
    await using var failed = new CentreDb(new DbContextOptionsBuilder<CentreDb>().UseNpgsql(DatabaseConnections.Configure(TestSettings.Load()["CC_TEST_DB_CONNECTION"])).AddInterceptors(fault).Options);
    var message = Envelope(); var eventId = Guid.Parse(JsonNode.Parse(message)!["event_id"]!.GetValue<string>());
    var record = new KafkaRecord("approvals.requested", message, new object());
    await new ApprovalConsumer(failed, new SchemaChecks(), new FakeDelay()).Handle(record, TestContext.Current.CancellationToken);
    Assert.False(await failed.ProcessedEvents.AnyAsync(x => x.EventId == eventId)); Assert.False(await failed.Approvals.AnyAsync(x => x.RequestEventId == eventId));
    var dlq = (await failed.Outbox.Where(x => x.Topic == "dlq.approvals.requested").ToListAsync(TestContext.Current.CancellationToken)).Single(x => x.Envelope.Contains(eventId.ToString()));
    await using var db = Database(); var row = Letter(JsonNode.Parse(dlq.Envelope)!["payload"]!["original_message"]!.GetValue<string>()); db.DeadLetters.Add(row); await db.SaveChangesAsync(TestContext.Current.CancellationToken);
    using var host = new Host(true); using var admin = host.Client(); Assert.Equal(HttpStatusCode.Accepted, (await admin.PostAsJsonAsync($"/api/admin/dead-letters/{row.Id}/replay", new { }, TestContext.Current.CancellationToken)).StatusCode);
    var replay = Assert.Single(host.Kafka.Published);
    await new ApprovalConsumer(db, new SchemaChecks(), new FakeDelay()).Handle(new(replay.Topic, replay.Value, new object()), TestContext.Current.CancellationToken);
    Assert.True(await db.Approvals.AnyAsync(x => x.RequestEventId == eventId)); Assert.True(await db.ProcessedEvents.AnyAsync(x => x.EventId == eventId));
  }
  [DatabaseFact]
  public async Task ReplayTableRefusesUpdateDeleteAndTruncateForBothRoles()
  {
    await Migrate();
    foreach (var owner in new[] { false, true })
      foreach (var sql in new[] { "UPDATE dead_letter_replays SET outcome='failed'", "DELETE FROM dead_letter_replays", "TRUNCATE dead_letter_replays" })
      {
        await using var db = Database(owner); await using var transaction = await db.Database.BeginTransactionAsync(TestContext.Current.CancellationToken);
        await Assert.ThrowsAnyAsync<Exception>(() => db.Database.ExecuteSqlRawAsync(sql, TestContext.Current.CancellationToken)); await transaction.RollbackAsync(TestContext.Current.CancellationToken);
      }
  }
  [DatabaseFact]
  public async Task OutboxPublishesRequestAuditUnderStoredTraceEvenAfterRequestEnds()
  {
    await Migrate(); var capture = new CapturedSpans();
    using var provider = Tracing.Configure(Sdk.CreateTracerProviderBuilder()).AddProcessor(new SimpleActivityExportProcessor(capture)).Build();
    using var host = new Host(true); using var admin = host.Client(); await using var db = Database();
    var row = Letter(); db.DeadLetters.Add(row); await db.SaveChangesAsync(TestContext.Current.CancellationToken); await admin.PostAsJsonAsync($"/api/admin/dead-letters/{row.Id}/replay", new { }, TestContext.Current.CancellationToken);
    var audit = (await db.Outbox.Where(x => x.Topic == "audit.events").ToListAsync(TestContext.Current.CancellationToken)).Single(x => x.Envelope.Contains("dead_letter.replayed") && x.Envelope.Contains(row.Id.ToString()));
    var trace = JsonNode.Parse(audit.Envelope)!["payload"]!["trace_id"]!.GetValue<string>();
    var fake = new FakeKafka(); var publisher = new OutboxPublisher(db, fake);
    for (var n = 0; n < 100 && !fake.Published.Any(x => x.Value == audit.Envelope); n++) await publisher.Publish(TestContext.Current.CancellationToken);
    var index = fake.Published.FindIndex(x => x.Value == audit.Envelope); Assert.True(index >= 0);
    Assert.Contains(trace, Tracing.Header(fake.Headers[index], "traceparent")!);
    Assert.Contains(capture.Spans, x => x.Kind == ActivityKind.Producer && x.TraceId.ToHexString() == trace);
  }
  [DatabaseFact]
  public async Task AuditProxyPreservesTraceIdAndForwardsValidatedFilter()
  {
    await Migrate();
    Environment.SetEnvironmentVariable("CC_AUDIT_WRITER_URL", "http://audit.invalid");
    try
    {
      using var host = new Host(true, "synthetic-client-secret"); using var admin = host.Client();
      const string traceId = "12345678901234567890123456789012";
      host.Gateway.Answer = _ => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = JsonContent.Create(new[] { new { user_id = "synthetic-user", trace_id = traceId } }) });
      var rows = await admin.GetFromJsonAsync<JsonArray>("/api/admin/trail?trace_id=" + traceId, TestContext.Current.CancellationToken);
      Assert.Equal(traceId, rows![0]!["trace_id"]!.GetValue<string>()); Assert.Equal("?trace_id=" + traceId, host.Gateway.GatewayQuery);
      var calls = host.Gateway.GatewayCalls;
      Assert.Equal(HttpStatusCode.BadRequest, (await admin.GetAsync("/api/admin/trail?trace_id=bad", TestContext.Current.CancellationToken)).StatusCode);
      Assert.Equal(calls, host.Gateway.GatewayCalls);
    }
    finally { Environment.SetEnvironmentVariable("CC_AUDIT_WRITER_URL", null); }
  }

  [DatabaseFact]
  public async Task ApprovalAndDeadLetterConsumersExtractKafkaContext()
  {
    await Migrate(); await using var db = Database(); var capture = new CapturedSpans();
    using var provider = Tracing.Configure(Sdk.CreateTracerProviderBuilder()).AddProcessor(new SimpleActivityExportProcessor(capture)).Build();
    const string traceId = "12345678901234567890123456789012"; const string parentId = "1234567890123456";
    var headers = new Headers { new Header("traceparent", System.Text.Encoding.UTF8.GetBytes("00-" + traceId + "-" + parentId + "-01")) };
    await new ApprovalConsumer(db, new SchemaChecks(), new FakeDelay()).Handle(new("approvals.requested", Envelope(), new object(), headers), TestContext.Current.CancellationToken);
    var position = new ConsumeResult<string, string> { Topic = "dlq.audit.events", Partition = 0, Offset = DateTimeOffset.UtcNow.Ticks };
    await new DeadLetterConsumer(db).Handle(new(position.Topic, "not json", position, headers), TestContext.Current.CancellationToken);
    Assert.Equal(2, capture.Spans.Count);
    Assert.All(capture.Spans, span => { Assert.Equal(ActivityKind.Consumer, span.Kind); Assert.Equal(traceId, span.TraceId.ToHexString()); Assert.Equal(parentId, span.ParentSpanId.ToHexString()); Assert.StartsWith("process ", span.DisplayName); });
  }

  private sealed class ReplayQueryCount : DbCommandInterceptor
  {
    public List<string> Reads { get; } = [];
    public override ValueTask<InterceptionResult<DbDataReader>> ReaderExecutingAsync(DbCommand command, CommandEventData eventData,
      InterceptionResult<DbDataReader> result, CancellationToken cancellationToken = default)
    {
      if (command.CommandText.Contains("FROM dead_letter_replays", StringComparison.Ordinal)) Reads.Add(command.CommandText);
      return base.ReaderExecutingAsync(command, eventData, result, cancellationToken);
    }
  }
  [DatabaseFact]
  public async Task ReplayHistoryForAnEntirePageUsesOneQueryAndKeepsPerLetterOrder()
  {
    await Migrate(); var count = new ReplayQueryCount();
    await using var db = new CentreDb(new DbContextOptionsBuilder<CentreDb>()
      .UseNpgsql(DatabaseConnections.Configure(TestSettings.Load()["CC_TEST_DB_CONNECTION"])).AddInterceptors(count).Options);
    var rows = new[] { Letter(), Letter(), Letter() }; db.DeadLetters.AddRange(rows);
    var first = new DeadLetterReplay { DeadLetterId = rows[0].Id, ReplayedBy = "synthetic", TargetTopic = "approvals.requested", Outcome = "sent", ReplayedAt = DateTimeOffset.UtcNow.AddMinutes(-1) };
    var last = new DeadLetterReplay { DeadLetterId = rows[0].Id, ReplayedBy = "synthetic", TargetTopic = "approvals.requested", Outcome = "failed", ReplayedAt = DateTimeOffset.FromUnixTimeMilliseconds(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()) };
    db.DeadLetterReplays.AddRange(first, last, new() { DeadLetterId = rows[1].Id, ReplayedBy = "synthetic", TargetTopic = "approvals.requested", Outcome = "sent" });
    await db.SaveChangesAsync(TestContext.Current.CancellationToken); count.Reads.Clear();
    var views = JsonNode.Parse(Api.Encode(await ReplayRoutes.Views(db, rows, TestContext.Current.CancellationToken)))!.AsArray();
    Assert.Contains("ANY", Assert.Single(count.Reads));
    Assert.Equal(new[] { 2, 1, 0 }, views.Select(x => x!["replay_count"]!.GetValue<int>()));
    Assert.Equal(last.Id.ToString(), views[0]!["replay_history"]![0]!["id"]!.GetValue<string>());
    Assert.Equal(last.ReplayedAt, views[0]!["last_replayed_at"]!.GetValue<DateTimeOffset>());
    Assert.Null(views[2]!["last_replayed_at"]); Assert.Empty(views[2]!["replay_history"]!.AsArray());
    count.Reads.Clear(); Assert.Empty(await ReplayRoutes.Views(db, [], TestContext.Current.CancellationToken)); Assert.Empty(count.Reads);
  }

}
