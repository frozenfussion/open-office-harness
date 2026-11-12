// SPDX-License-Identifier: AGPL-3.0-only
using System.Text.Json;
using System.Text.Json.Nodes;
using Confluent.Kafka;
using Microsoft.EntityFrameworkCore;

namespace ControlCentre.Platform;

public sealed class DeadLetterConsumer(CentreDb db)
{
  public static readonly string[] Topics = ["dlq.skill.requests.slides", "dlq.skill.results", "dlq.approvals.requested", "dlq.approvals.decided", "dlq.audit.events", "dlq.chat.messages"];
  public async Task Handle(KafkaRecord record, CancellationToken ct)
  {
    using var span = Tracing.Start(record.Topic, System.Diagnostics.ActivityKind.Consumer, Tracing.Header(record.Headers, "traceparent") ?? "", Tracing.Header(record.Headers, "tracestate"));
    var position = (ConsumeResult<string, string>)record.Position;
    var partition = position.Partition.Value; var offset = position.Offset.Value;
    if (await db.DeadLetters.AnyAsync(x => x.Topic == record.Topic && x.Partition == partition && x.Offset == offset, ct)) return;
    JsonObject? node = null;
    try { node = JsonNode.Parse(record.Value) as JsonObject; } catch (JsonException) { }
    string? Text(JsonNode? value) => value is JsonValue v && v.TryGetValue<string>(out var text) ? text : null;
    var payload = node?["payload"] as JsonObject;
    var error = payload?["error"] as JsonObject;
    var correlation = Guid.TryParse(Text(node?["correlation_id"]), out var id) ? id : (Guid?)null;
    // The unique broker position also deduplicates unreadable dead letters without event ids.
    await db.Database.ExecuteSqlInterpolatedAsync($"""
      INSERT INTO dead_letters (id, topic, partition, "offset", received_at, error_code, error_message, original_message, correlation_id)
      VALUES ({Guid.NewGuid()}, {record.Topic}, {partition}, {offset}, {DateTimeOffset.UtcNow},
        {Text(error?["code"]) ?? "invalid_event"}, {Text(error?["message"]) ?? "Invalid dead letter"},
        {Text(payload?["original_message"]) ?? record.Value}, {correlation})
      ON CONFLICT (topic, partition, "offset") DO NOTHING
      """, ct);
  }
}
