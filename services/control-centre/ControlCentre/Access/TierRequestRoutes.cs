// SPDX-License-Identifier: AGPL-3.0-only
using System.Text.Json.Nodes;
using ControlCentre.Platform;
using ControlCentre.Registry;
using Microsoft.EntityFrameworkCore;

namespace ControlCentre.Access;

public static class TierRequestRoutes
{
  public static void Audit(CentreDb db, TierRequest row, string action, string actor, Guid correlation) => Api.Change(db, actor, action, row.UserId, correlation,
    new JsonObject { ["user_id"] = row.UserId, ["tier"] = row.Tier, ["status"] = row.Status, ["decided_by"] = row.DecidedBy }, row.UserId);
  public static void Map(WebApplication app)
  {
    app.MapPost("/api/tier-requests", async (HttpContext c, CentreDb db, TimeProvider clock) =>
    {
      if (!Api.Service(c.User, "ooh-harness-api")) throw new ApiException(403, "forbidden", "Harness service account required");
      Api.Query(c); var body = await Api.Body(c, ["user_id", "tier"], "reason");
      var user = Api.String(body, "user_id"); var tier = Api.Value<int>(body, "tier");
      var reason = body["reason"] is null ? null : Api.Value<string>(body, "reason").Trim();
      Api.Require(reason is null || reason.Length <= 300, "reason is too long");
      await using var transaction = await db.Database.BeginTransactionAsync(); await AccessPolicy.Lock(db);
      if (!await AccessPolicy.Approved(db, user)) throw new ApiException(403, "not_approved", "Your access is not approved");
      var choice = (await TierChoices.Requestable(db, user)).SingleOrDefault(x => x.Tier == tier);
      if (choice is null) throw new ApiException(400, "tier_not_requestable", "This tier cannot be requested");
      if (choice.Requested == "pending") throw new ApiException(409, "already_requested", "This tier is already requested");
      var latest = await db.TierRequests.Where(x => x.UserId == user && x.Tier == tier && x.DeletedAt == null).OrderByDescending(x => x.RequestedAt).ThenByDescending(x => x.Id).FirstOrDefaultAsync();
      if (latest is { Status: "rejected" } && (latest.DecidedAt ?? latest.RequestedAt) > clock.GetUtcNow().AddDays(-7))
        throw new ApiException(400, "tier_not_requestable", "Wait seven days after rejection before requesting this tier again");
      if (await db.TierRequests.CountAsync(x => x.UserId == user && x.Status == "pending" && x.DeletedAt == null) >= 20)
        throw new ApiException(429, "too_many_requests", "You already have 20 waiting model requests");
      var row = new TierRequest { UserId = user, Tier = tier, Reason = reason, RequestedAt = clock.GetUtcNow() };
      Api.Stamp(row, Api.Actor(c), true); db.TierRequests.Add(row); Audit(db, row, "tier.requested", Api.Actor(c), Api.Correlation(c));
      await db.SaveChangesAsync(); await transaction.CommitAsync(); return Results.Json(new { row.Id, row.Status }, statusCode: 201);
    }).RequireAuthorization();
    app.MapGet("/api/admin/tier-requests/count", async (HttpContext c, CentreDb db) =>
    {
      Api.Authorize(c); Api.Query(c, "status"); Api.Require(Api.Q(c, "status") == "pending");
      return Results.Ok(new { count = await db.TierRequests.CountAsync(x => x.DeletedAt == null && x.Status == "pending" && !x.UserId.StartsWith("stage-check-")) });
    }).RequireAuthorization();
    app.MapGet("/api/admin/tier-requests", async (HttpContext c, CentreDb db) =>
    {
      Api.Authorize(c); Api.Query(c, "status", "limit", "after");
      var status = c.Request.Query.ContainsKey("status") ? Api.Q(c, "status") : "pending"; Api.Require(status is "pending" or "approved" or "rejected");
      var limit = Api.Limit(c); var query = db.TierRequests.Where(x => x.DeletedAt == null && x.Status == status && !x.UserId.StartsWith("stage-check-"));
      if (c.Request.Query.ContainsKey("after"))
      {
        var id = Api.Id(Api.Q(c, "after")); var cursor = await db.TierRequests.AsNoTracking().SingleOrDefaultAsync(x => x.Id == id && !x.UserId.StartsWith("stage-check-")); Api.Found(cursor is not null);
        var at = cursor!.RequestedAt; query = query.Where(x => x.RequestedAt < at || x.RequestedAt == at && x.Id.CompareTo(id) < 0);
      }
      return Results.Ok(await View(db, await query.OrderByDescending(x => x.RequestedAt).ThenByDescending(x => x.Id).Take(limit).ToListAsync()));
    }).RequireAuthorization();
    app.MapPost("/api/admin/tier-requests/{id}/approve", async (string id, HttpContext c, CentreDb db, TimeProvider clock) => await Decide(id, c, db, clock, true)).RequireAuthorization();
    app.MapPost("/api/admin/tier-requests/{id}/reject", async (string id, HttpContext c, CentreDb db, TimeProvider clock) => await Decide(id, c, db, clock, false)).RequireAuthorization();
  }
  private static async Task<IResult> Decide(string id, HttpContext c, CentreDb db, TimeProvider clock, bool approve)
  {
    Api.Authorize(c); Api.Query(c);
    if (c.Request.ContentLength is > 0 || c.Request.Headers.ContainsKey("Transfer-Encoding")) await Api.Body(c, []);
    var keyId = Api.Id(id);
    await using var transaction = await db.Database.BeginTransactionAsync(); await AccessPolicy.Lock(db);
    var row = await db.TierRequests.FindAsync(keyId); Api.Found(row is { DeletedAt: null } && !row.UserId.StartsWith("stage-check-", StringComparison.Ordinal));
    if (row!.Status != "pending") throw new ApiException(409, "conflict", "Model request is already decided");
    if (!await AccessPolicy.Approved(db, row.UserId)) throw new ApiException(409, "not_approved", "This person's access is no longer approved");
    if (approve)
    {
      var key = "chat.tier." + row.Tier;
      Api.Require(await db.Rights.AnyAsync(x => x.Key == key && x.DeletedAt == null), "Unknown tier");
      await People.Ensure(db, row.UserId, Api.Actor(c), Api.Correlation(c));
      if (!await db.Grants.AnyAsync(x => x.RightKey == key && x.SubjectType == "user" && x.SubjectId == row.UserId && x.DeletedAt == null))
      {
        var grant = new Grant { RightKey = key, SubjectType = "user", SubjectId = row.UserId }; Api.Stamp(grant, Api.Actor(c), true); db.Grants.Add(grant);
        Api.Change(db, Api.Actor(c), "grant.created", key, Api.Correlation(c), new { after = grant });
      }
    }
    row.Status = approve ? "approved" : "rejected"; row.DecidedAt = clock.GetUtcNow(); row.DecidedBy = Api.Actor(c); Api.Stamp(row, Api.Actor(c));
    Audit(db, row, approve ? "tier.approved" : "tier.rejected", Api.Actor(c), Api.Correlation(c));
    await db.SaveChangesAsync(); await transaction.CommitAsync(); return Results.Ok((await View(db, [row])).Single());
  }
  private static async Task<List<object>> View(CentreDb db, List<TierRequest> rows)
  {
    var users = rows.Select(x => x.UserId).Distinct().ToArray();
    var profiles = await db.AccessRequests.Where(x => x.DeletedAt == null && users.Contains(x.UserId)).ToDictionaryAsync(x => x.UserId);
    var main = (await TierChoices.MainEntries(db)).ToDictionary(x => x.Tier);
    return rows.Select(row =>
    {
      profiles.TryGetValue(row.UserId, out var profile); main.TryGetValue(row.Tier, out var model);
      return (object)new
      {
        row.Id,
        row.UserId,
        row.Tier,
        title = model?.Title ?? "",
        name = string.IsNullOrEmpty(profile?.Name) ? row.UserId : profile.Name,
        email = string.IsNullOrEmpty(profile?.Email) ? row.UserId : profile.Email,
        row.Reason,
        row.Status,
        row.RequestedAt,
        row.DecidedAt,
        row.DecidedBy,
        row.CreatedAt,
        row.UpdatedAt,
        row.CreatedBy,
        row.UpdatedBy,
        row.DeletedAt
      };
    }).ToList();
  }
}
