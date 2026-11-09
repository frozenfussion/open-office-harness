// SPDX-License-Identifier: AGPL-3.0-only
using System.Globalization;
using ControlCentre.Platform;
using Microsoft.EntityFrameworkCore;

namespace ControlCentre.Approvals;

public static class ApprovalRoutes
{
  public static object View(Approval row)
  {
    var value = System.Text.Json.Nodes.JsonNode.Parse(Api.Encode(row))!.AsObject();
    value["details"] = System.Text.Json.Nodes.JsonNode.Parse(row.Details);
    return value;
  }
  public static void Map(WebApplication app)
  {
    app.MapGet("/api/admin/approvals", async (HttpContext c, CentreDb db) =>
    {
      Api.Authorize(c); Api.Query(c, "status", "correlation_id", "limit", "before");
      var limit = Api.Limit(c);
      var query = db.Approvals.Where(x => x.DeletedAt == null);
      if (c.Request.Query.ContainsKey("status"))
      {
        var status = Api.Q(c, "status");
        Api.Require(status is "pending" or "approved" or "rejected");
        query = query.Where(x => x.Status == status);
      }
      if (c.Request.Query.ContainsKey("correlation_id"))
      {
        var correlation = Api.Id(Api.Q(c, "correlation_id"));
        query = query.Where(x => x.CorrelationId == correlation);
      }
      if (c.Request.Query.ContainsKey("before"))
      {
        var parts = Api.Q(c, "before").Split(',');
        Api.Require(parts.Length == 2, "before must be <UTC timestamp>,<id>");
        Api.Require(DateTimeOffset.TryParse(parts[0], CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind, out var timestamp) && timestamp.Offset == TimeSpan.Zero);
        var id = Api.Id(parts[1]);
        query = query.Where(x => x.CreatedAt < timestamp || (x.CreatedAt == timestamp && x.Id.CompareTo(id) < 0));
      }
      return Results.Ok((await query.OrderByDescending(x => x.CreatedAt).ThenByDescending(x => x.Id).Take(limit).ToListAsync()).Select(View));
    }).RequireAuthorization();
    app.MapGet("/api/admin/approvals/{id}", async (string id, HttpContext c, CentreDb db) =>
    {
      Api.Authorize(c); Api.Query(c);
      var row = await db.Approvals.FindAsync(Api.Id(id));
      Api.Found(row is not null && row.DeletedAt == null);
      return Results.Ok(View(row!));
    }).RequireAuthorization();
    app.MapPost("/api/admin/approvals/{id}/decision", async (string id, HttpContext c, CentreDb db) =>
    {
      Api.Authorize(c); Api.Query(c);
      var key = Api.Id(id);
      var body = await Api.Body(c, ["approved", "note"]);
      var approved = Api.Value<bool>(body, "approved");
      var note = Api.Value<string>(body, "note");
      var row = await db.Approvals.FindAsync(key);
      Api.Found(row is not null && row.DeletedAt == null);
      if (row!.Status != "pending") throw new ApiException(409, "conflict", "Approval already decided");
      var before = System.Text.Json.Nodes.JsonNode.Parse(Api.Encode(row));
      row.Status = approved ? "approved" : "rejected";
      row.Note = note;
      row.DecidedBy = Api.Actor(c);
      row.DecidedAt = DateTimeOffset.UtcNow;
      Api.Stamp(row, Api.Actor(c));
      Api.Change(db, Api.Actor(c), "approval.decided", row.Id.ToString(), Api.Correlation(c), new { before, after = row });
      Api.Event(db, "approvals.decided", "approval.decided", row.CorrelationId, row.RequesterUserId, new { approved, decided_by = Api.Actor(c), note });
      await db.SaveChangesAsync();
      return Results.Ok(View(row!));
    }).RequireAuthorization();
  }
}
