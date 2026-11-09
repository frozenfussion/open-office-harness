// SPDX-License-Identifier: AGPL-3.0-only
using System.Text.Json.Nodes;
using Confluent.Kafka;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace ControlCentre.Platform;

public sealed record KafkaRecord(string Topic, string Value, object Position);
public interface IKafka
{
  Task Publish(string topic, string key, string value, CancellationToken ct);
  KafkaRecord? Read(CancellationToken ct);
  void Commit(KafkaRecord record);
}
public interface IRetryDelay { Task Wait(TimeSpan duration, CancellationToken ct); }
public sealed class RetryDelay : IRetryDelay
{
  public Task Wait(TimeSpan duration, CancellationToken ct) => Task.Delay(duration, ct);
}
public sealed class KafkaClient : IKafka, IDisposable
{
  private readonly IProducer<string, string> producer;
  private readonly IConsumer<string, string> consumer;
  public KafkaClient()
  {
    string Required(string name) => Environment.GetEnvironmentVariable(name) is { Length: > 0 } value ? value : throw new InvalidOperationException($"Missing environment variable {name}");
    var config = new ClientConfig
    {
      BootstrapServers = Required("CC_KAFKA_BOOTSTRAP"),
      SecurityProtocol = SecurityProtocol.SaslPlaintext,
      SaslMechanism = SaslMechanism.ScramSha512,
      SaslUsername = Required("CC_KAFKA_USERNAME"),
      SaslPassword = Required("CC_KAFKA_PASSWORD")
    };
    producer = new ProducerBuilder<string, string>(new ProducerConfig(config) { EnableIdempotence = true, Acks = Acks.All, MessageTimeoutMs = 10000 }).SetLogHandler((_, _) => { }).SetErrorHandler((_, _) => { }).Build();
    consumer = new ConsumerBuilder<string, string>(new ConsumerConfig(config)
    {
      GroupId = "control-centre",
      EnableAutoCommit = false,
      EnableAutoOffsetStore = false,
      AutoOffsetReset = AutoOffsetReset.Earliest
    }).SetLogHandler((_, _) => { }).SetErrorHandler((_, _) => { }).Build();
    consumer.Subscribe("approvals.requested");
  }
  public async Task Publish(string topic, string key, string value, CancellationToken ct) =>
      await producer.ProduceAsync(topic, new Message<string, string> { Key = key, Value = value }, ct);
  public KafkaRecord? Read(CancellationToken ct)
  {
    ct.ThrowIfCancellationRequested();
    var record = consumer.Consume(TimeSpan.FromMilliseconds(100));
    return record is null ? null : new KafkaRecord(record.Topic, record.Message.Value, record);
  }
  public void Commit(KafkaRecord record) => consumer.Commit((ConsumeResult<string, string>)record.Position);
  public void Dispose() { consumer.Close(); consumer.Dispose(); producer.Dispose(); }
}

public sealed class OutboxPublisher(CentreDb db, IKafka kafka)
{
  public async Task Publish(CancellationToken ct)
  {
    // Row locks keep concurrent replicas from publishing the same pending row at once.
    await using var transaction = await db.Database.BeginTransactionAsync(ct);
    var rows = await db.Outbox.FromSqlRaw("SELECT * FROM outbox WHERE sent_at IS NULL ORDER BY created_at, id LIMIT 50 FOR UPDATE SKIP LOCKED").ToListAsync(ct);
    foreach (var row in rows)
    {
      await kafka.Publish(row.Topic, row.Key, row.Envelope, ct);
      row.SentAt = DateTimeOffset.UtcNow;
    }
    await db.SaveChangesAsync(ct);
    await transaction.CommitAsync(ct);
  }
}

public sealed class ApprovalConsumer(CentreDb db, SchemaChecks schemas, IRetryDelay delay)
{
  public async Task Handle(KafkaRecord record, CancellationToken ct)
  {
    JsonNode? node = null;
    try
    {
      using var document = System.Text.Json.JsonDocument.Parse(record.Value ?? "");
      if (UniqueFields(document.RootElement)) node = JsonNode.Parse(document.RootElement.GetRawText());
    }
    catch (System.Text.Json.JsonException) { }
    node = node as JsonObject;
    var valid = schemas.Envelope(node);
    var waits = new[] { 1, 5, 15 };
    for (var attempt = 0; valid && attempt < waits.Length; attempt++)
    {
      try { await Process(record, node, ct); return; }
      catch (OperationCanceledException) when (ct.IsCancellationRequested) { throw; }
      catch (Exception)
      {
        db.ChangeTracker.Clear();
        await delay.Wait(TimeSpan.FromSeconds(waits[attempt]), ct);
      }
    }
    Guid? eventId = Guid.TryParse(node?["event_id"]?.ToString(), out var parsedId) ? parsedId : null;
    var correlation = Guid.TryParse(node?["correlation_id"]?.ToString(), out var parsedCorrelation) ? parsedCorrelation : Guid.NewGuid();
    var user = node?["user_id"] is JsonValue userValue && userValue.TryGetValue<string>(out var parsedUser) && !string.IsNullOrWhiteSpace(parsedUser) ? parsedUser : "system";
    if (eventId is not null && await db.ProcessedEvents.AnyAsync(x => x.EventId == eventId, ct)) return;
    if (eventId is not null) db.ProcessedEvents.Add(new ProcessedEvent { EventId = eventId.Value, Topic = record.Topic });
    Api.Event(db, "dlq.approvals.requested", "dlq.entry", correlation, user, new { original_message = string.IsNullOrEmpty(record.Value) ? "<empty>" : record.Value, error = new { code = valid ? "processing_failed" : "invalid_event", message = valid ? "Approval request failed after three attempts" : "Invalid approval request" } });
    Api.Change(db, "system", "approval.failed", eventId?.ToString() ?? "unreadable", correlation, new { outcome = "dlq" }, user);
    await db.SaveChangesAsync(ct);
  }
  private static bool UniqueFields(System.Text.Json.JsonElement value) => value.ValueKind switch
  {
    System.Text.Json.JsonValueKind.Object => value.EnumerateObject().Select(x => x.Name).Distinct().Count() == value.EnumerateObject().Count() && value.EnumerateObject().All(x => UniqueFields(x.Value)),
    System.Text.Json.JsonValueKind.Array => value.EnumerateArray().All(UniqueFields),
    _ => true
  };
  private async Task Process(KafkaRecord record, JsonNode? node, CancellationToken ct)
  {
    if (!schemas.Envelope(node)) throw new ApiException(400, "invalid_event", "Invalid approval request");
    var value = node!;
    var id = Guid.Parse(value["event_id"]!.GetValue<string>());
    if (await db.ProcessedEvents.AnyAsync(x => x.EventId == id, ct)) return;
    var correlation = Guid.Parse(value["correlation_id"]!.GetValue<string>());
    var user = value["user_id"]!.GetValue<string>();
    var payload = value["payload"]!;
    var approval = new Approval
    {
      RequestEventId = id,
      CorrelationId = correlation,
      RequesterUserId = user,
      Producer = value["producer"]!.GetValue<string>(),
      Action = payload["action"]!.GetValue<string>(),
      Details = payload["details"]!.ToJsonString(),
      Risk = payload["risk"]!.GetValue<string>(),
      RequestedBy = payload["requested_by"]!.GetValue<string>()
    };
    db.Approvals.Add(approval);
    db.ProcessedEvents.Add(new ProcessedEvent { EventId = id, Topic = record.Topic });
    Api.Change(db, "system", "approval.requested", approval.Id.ToString(), correlation, new { after = approval }, user);
    try { await db.SaveChangesAsync(ct); }
    catch (DbUpdateException e) when (e.InnerException is PostgresException { SqlState: "23505" })
    {
      db.ChangeTracker.Clear();
      if (!await db.ProcessedEvents.AnyAsync(x => x.EventId == id, ct)) throw;
    }
  }
}

public sealed class KafkaWorker(IServiceScopeFactory scopes, IKafka kafka, ILogger<KafkaWorker> logger) : BackgroundService
{
  protected override async Task ExecuteAsync(CancellationToken stoppingToken)
  {
    await Task.Yield();
    KafkaRecord? pending = null;
    while (!stoppingToken.IsCancellationRequested)
    {
      try
      {
        using var scope = scopes.CreateScope();
        await scope.ServiceProvider.GetRequiredService<OutboxPublisher>().Publish(stoppingToken);
        pending ??= kafka.Read(stoppingToken);
        if (pending is not null)
        {
          await scope.ServiceProvider.GetRequiredService<ApprovalConsumer>().Handle(pending, stoppingToken);
          kafka.Commit(pending);
          pending = null;
        }
      }
      catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested) { break; }
      catch (Exception error)
      {
        Diagnostics.Failure(logger, "Kafka work deferred; will retry", error);
        await Task.Delay(TimeSpan.FromSeconds(1), stoppingToken);
      }
    }
  }
}
