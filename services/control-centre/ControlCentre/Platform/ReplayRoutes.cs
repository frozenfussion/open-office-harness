// SPDX-License-Identifier: AGPL-3.0-only
using System.Text.Json;
using Microsoft.EntityFrameworkCore;

namespace ControlCentre.Platform;

public static class ReplayRoutes
{
  public static bool Replayable(DeadLetter row)
  {
    if (row.Topic == "dlq.chat.messages" || !DeadLetterConsumer.Topics.Contains(row.Topic)) return false;
    try
    {
      using var doc = JsonDocument.Parse(row.OriginalMessage);
      return doc.RootElement.ValueKind == JsonValueKind.Object && doc.RootElement.TryGetProperty("correlation_id", out var correlation)
        && correlation.ValueKind == JsonValueKind.String && Guid.TryParse(correlation.GetString(), out _);
    }
    catch (JsonException) { return false; }
  }
  public static async Task<object[]> Views(CentreDb db, IReadOnlyList<DeadLetter> rows, CancellationToken ct)
  {
    if (rows.Count == 0) return [];
    var ids = rows.Select(x => x.Id).ToArray();
    var history = await db.DeadLetterReplays.AsNoTracking().Where(x => ids.Contains(x.DeadLetterId))
      .OrderByDescending(x => x.ReplayedAt).ThenByDescending(x => x.Id).ToListAsync(ct);
    var grouped = history.ToLookup(x => x.DeadLetterId);
    return rows.Select(row => View(row, grouped[row.Id].ToArray())).ToArray();
  }
  private static object View(DeadLetter row, DeadLetterReplay[] history) => new
  {
    row.Id,
    row.Topic,
    row.Partition,
    row.Offset,
    row.ReceivedAt,
    row.ErrorCode,
    row.ErrorMessage,
    row.OriginalMessage,
    row.CorrelationId,
    replay_count = history.Length,
    last_replayed_at = history.FirstOrDefault()?.ReplayedAt,
    replayable = Replayable(row),
    replay_history = history
  };
  public static void Map(WebApplication app)
  {
    app.MapPost("/api/admin/dead-letters/{id}/replay", async (string id, HttpContext c, CentreDb db, IKafka kafka) =>
    {
      Api.Authorize(c); Api.Query(c); var key = Api.Id(id);
      var row = await db.DeadLetters.SingleOrDefaultAsync(x => x.Id == key, c.RequestAborted); Api.Found(row is not null);
      if (!Replayable(row!)) return Api.Error(409, "not_replayable", "This message cannot be replayed");
      using var doc = JsonDocument.Parse(row!.OriginalMessage);
      // A replay must keep the original envelope and its correlation key exactly.
      if (doc.RootElement.ValueKind != JsonValueKind.Object || !doc.RootElement.TryGetProperty("correlation_id", out var correlationValue)
        || correlationValue.ValueKind != JsonValueKind.String || !Guid.TryParse(correlationValue.GetString(), out var correlation))
        return Api.Error(409, "not_replayable", "The original message has no request ID");
      var replay = new DeadLetterReplay { DeadLetterId = row.Id, ReplayedBy = Api.Actor(c), TargetTopic = row.Topic[4..], Outcome = "sent" };
      using (var send = Tracing.Start(replay.TargetTopic, System.Diagnostics.ActivityKind.Producer))
      {
        try { await kafka.Publish(replay.TargetTopic, correlationValue.GetString()!, row.OriginalMessage, c.RequestAborted); }
        catch (Exception e) when (e is not OperationCanceledException || !c.RequestAborted.IsCancellationRequested)
        {
          replay.Outcome = "failed"; replay.ErrorCode = "kafka_unavailable";
          send?.SetTag("ooh.error_code", replay.ErrorCode); send?.SetStatus(System.Diagnostics.ActivityStatusCode.Error);
        }
      }
      db.DeadLetterReplays.Add(replay);
      Api.Change(db, Api.Actor(c), "dead_letter.replayed", row.Id.ToString(), Api.Correlation(c), new { dead_letter_id = row.Id, replay_id = replay.Id, target_topic = replay.TargetTopic }, outcome: replay.Outcome == "sent" ? "success" : "failed");
      await db.SaveChangesAsync(c.RequestAborted);
      return replay.Outcome == "sent" ? Results.Json(new { replay_id = replay.Id, target_topic = replay.TargetTopic, outcome = replay.Outcome }, statusCode: 202)
        : Api.Error(503, "kafka_unavailable", "Kafka is unavailable; the replay was recorded");
    }).RequireAuthorization();
  }
}
