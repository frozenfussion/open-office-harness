// SPDX-License-Identifier: AGPL-3.0-only
using System.Text.Json.Nodes;
using ControlCentre.Platform;
using Microsoft.EntityFrameworkCore;

namespace ControlCentre.Access;

public static class AccessRoutes
{
  private static string? Profile(JsonObject body, string field, int limit)
  {
    if (body[field] is null) return null;
    var text = Api.Value<string>(body, field).Trim();
    Api.Require(text.Length <= limit, field + " is too long");
    return text;
  }
  private static async Task EmptyBody(HttpContext c)
  {
    if (c.Request.ContentLength is > 0 || c.Request.Headers.ContainsKey("Transfer-Encoding")) await Api.Body(c, []);
  }
  public static void Map(WebApplication app)
  {
    app.MapPost("/api/access/observe", async (HttpContext c, CentreDb db) =>
    {
      if (!Api.Service(c.User, "ooh-harness-api")) throw new ApiException(403, "forbidden", "Harness service account required");
      Api.Query(c);
      var body = await Api.Body(c, ["user_id", "is_admin"], "name", "email", "organisation", "access_reason", "is_service_account");
      var userId = Api.String(body, "user_id");
      var admin = Api.Value<bool>(body, "is_admin");
      var service = body.ContainsKey("is_service_account") && Api.Value<bool>(body, "is_service_account");
      var name = Profile(body, "name", 200); var email = Profile(body, "email", 320);
      var organisation = Profile(body, "organisation", 100); var reason = Profile(body, "access_reason", 300);
      await using var transaction = await db.Database.BeginTransactionAsync();
      await AccessPolicy.Lock(db);
      var row = await db.AccessRequests.SingleOrDefaultAsync(x => x.UserId == userId);
      if (row is null)
      {
        if (!admin && await db.AccessRequests.CountAsync(x => x.Status == "pending" && x.DeletedAt == null) >= 100)
          return Results.Ok(new { status = "closed" });
        row = new AccessRequest { UserId = userId, IsServiceAccount = service, Name = name, Email = email, Organisation = organisation, Reason = reason };
        Api.Stamp(row, Api.Actor(c), true); db.AccessRequests.Add(row);
        if (admin)
        { row.Status = "approved"; row.DecidedBy = "system:admin-role"; row.DecidedAt = DateTimeOffset.UtcNow; }
        AccessPolicy.Audit(db, row, admin ? "access.approved" : "access.requested", Api.Actor(c), Api.Correlation(c));
      }
      else
      {
        if (row.Status == "pending" && (row.Name != name || row.Email != email || row.Organisation != organisation || row.Reason != reason))
        {
          row.Name = name; row.Email = email; row.Organisation = organisation; row.Reason = reason;
          Api.Stamp(row, Api.Actor(c));
          AccessPolicy.Audit(db, row, "access.requested", Api.Actor(c), Api.Correlation(c));
        }
        if (admin && row.Status != "approved") row = await AccessPolicy.Approve(db, userId, Api.Actor(c), "system:admin-role", Api.Correlation(c));
      }
      row.IsServiceAccount = service;
      var (person, _) = await People.Ensure(db, userId, Api.Actor(c), Api.Correlation(c));
      person.IsServiceAccount = service;
      await db.SaveChangesAsync(); await transaction.CommitAsync();
      return Results.Ok(new { status = row.Status });
    }).RequireAuthorization();
    app.MapGet("/api/admin/access-requests/count", async (HttpContext c, CentreDb db) =>
    {
      Api.Authorize(c); Api.Query(c, "status"); Api.Require(Api.Q(c, "status") == "pending");
      return Results.Ok(new { count = await db.AccessRequests.CountAsync(x => x.DeletedAt == null && x.Status == "pending" && !x.UserId.StartsWith("stage-check-") && !x.UserId.StartsWith("service-account-") && !db.People.Any(p => p.UserId == x.UserId && p.IsServiceAccount) && !db.AccessRequests.Any(a => a.UserId == x.UserId && a.IsServiceAccount)) });
    }).RequireAuthorization();
    app.MapGet("/api/admin/access-requests", async (HttpContext c, CentreDb db) =>
    {
      Api.Authorize(c); Api.Query(c, "status", "limit", "after");
      var status = c.Request.Query.ContainsKey("status") ? Api.Q(c, "status") : "pending";
      Api.Require(status is "pending" or "approved" or "rejected");
      var limit = Api.Limit(c);
      var query = db.AccessRequests.Where(x => x.DeletedAt == null && x.Status == status && !x.UserId.StartsWith("stage-check-") && !x.UserId.StartsWith("service-account-") && !db.People.Any(p => p.UserId == x.UserId && p.IsServiceAccount) && !db.AccessRequests.Any(a => a.UserId == x.UserId && a.IsServiceAccount));
      if (c.Request.Query.ContainsKey("after"))
      {
        var id = Api.Id(Api.Q(c, "after"));
        var cursor = await db.AccessRequests.AsNoTracking().SingleOrDefaultAsync(x => x.Id == id && !x.UserId.StartsWith("stage-check-") && !x.UserId.StartsWith("service-account-") && !db.People.Any(p => p.UserId == x.UserId && p.IsServiceAccount) && !db.AccessRequests.Any(a => a.UserId == x.UserId && a.IsServiceAccount));
        Api.Found(cursor is not null);
        var at = cursor!.RequestedAt;
        query = query.Where(x => x.RequestedAt < at || x.RequestedAt == at && x.Id.CompareTo(id) < 0);
      }
      return Results.Ok(await query.OrderByDescending(x => x.RequestedAt).ThenByDescending(x => x.Id).Take(limit).ToListAsync());
    }).RequireAuthorization();
    app.MapPost("/api/admin/access-requests/{id}/approve", async (string id, HttpContext c, CentreDb db) =>
    {
      Api.Authorize(c); Api.Query(c);
      var body = await Api.Body(c, ["tier"]); var tier = Api.Value<int>(body, "tier"); Api.Require(tier > 0);
      var key = "chat.tier." + tier;
      await using var transaction = await db.Database.BeginTransactionAsync(); await AccessPolicy.Lock(db);
      var row = await db.AccessRequests.FindAsync(Api.Id(id)); Api.Found(row is { DeletedAt: null });
      if (row!.Status == "approved") throw new ApiException(409, "conflict", "Access is already approved");
      Api.Require(await db.Rights.AnyAsync(x => x.Key == key && x.DeletedAt == null), "Unknown tier");
      await People.Ensure(db, row.UserId, Api.Actor(c), Api.Correlation(c));
      await AccessPolicy.Approve(db, row.UserId, Api.Actor(c), Api.Actor(c), Api.Correlation(c), tier);
      if (!await db.Grants.AnyAsync(x => x.RightKey == key && x.SubjectType == "user" && x.SubjectId == row.UserId && x.DeletedAt == null))
      {
        var grant = new Grant { RightKey = key, SubjectType = "user", SubjectId = row.UserId };
        Api.Stamp(grant, Api.Actor(c), true); db.Grants.Add(grant);
        Api.Change(db, Api.Actor(c), "grant.created", key, Api.Correlation(c), new { after = grant });
      }
      await db.SaveChangesAsync(); await transaction.CommitAsync(); return Results.Ok(row);
    }).RequireAuthorization();
    app.MapPost("/api/admin/access-requests/{id}/reject", async (string id, HttpContext c, CentreDb db) => await Refuse(id, c, db, false)).RequireAuthorization();
    app.MapPost("/api/admin/access-requests/{id}/revoke", async (string id, HttpContext c, CentreDb db) => await Refuse(id, c, db, true)).RequireAuthorization();
  }
  private static async Task<IResult> Refuse(string id, HttpContext c, CentreDb db, bool revoke)
  {
    Api.Authorize(c); Api.Query(c); await EmptyBody(c);
    await using var transaction = await db.Database.BeginTransactionAsync(); await AccessPolicy.Lock(db);
    var row = await db.AccessRequests.FindAsync(Api.Id(id)); Api.Found(row is { DeletedAt: null });
    if (row!.Status != (revoke ? "approved" : "pending")) throw new ApiException(409, "conflict", "Access request changed; reload the list");
    row.Status = "rejected"; row.DecidedAt = DateTimeOffset.UtcNow; row.DecidedBy = Api.Actor(c); Api.Stamp(row, Api.Actor(c));
    AccessPolicy.Audit(db, row, revoke ? "access.revoked" : "access.rejected", Api.Actor(c), Api.Correlation(c));
    await db.SaveChangesAsync(); await transaction.CommitAsync(); return Results.Ok(row);
  }
}
