// SPDX-License-Identifier: AGPL-3.0-only
using System.Text.Json.Nodes;
using ControlCentre.Platform;
using Microsoft.EntityFrameworkCore;

namespace ControlCentre.Access;

public static class AccessPolicy
{
  public static Task<bool> Approved(CentreDb db, string userId) => db.AccessRequests.AnyAsync(x => x.UserId == userId && x.DeletedAt == null && x.Status == "approved");
  public static async Task Lock(CentreDb db)
  {
    if (db.Database.CurrentTransaction is null) throw new InvalidOperationException("Access changes require a transaction");
    // One admission lock keeps the pending cap and status/grant changes atomic across replicas.
    await db.Database.ExecuteSqlRawAsync("SELECT pg_advisory_xact_lock(hashtext('ooh.access_requests'))");
  }
  public static void Audit(CentreDb db, AccessRequest row, string action, string actor, Guid correlation) => Api.Change(db, actor, action, row.UserId, correlation,
    new JsonObject { ["user_id"] = row.UserId, ["status"] = row.Status, ["decided_by"] = row.DecidedBy, ["approved_tier"] = row.ApprovedTier }, row.UserId);
  public static async Task<AccessRequest> Approve(CentreDb db, string userId, string actor, string decidedBy, Guid correlation, int? tier = null)
  {
    var row = await db.AccessRequests.SingleOrDefaultAsync(x => x.UserId == userId);
    if (row is { Status: "approved", DeletedAt: null }) return row;
    var created = row is null;
    row ??= new AccessRequest { UserId = userId };
    row.Status = "approved"; row.DecidedAt = DateTimeOffset.UtcNow; row.DecidedBy = decidedBy;
    row.DeletedAt = null;
    if (tier is not null) row.ApprovedTier = tier;
    Api.Stamp(row, actor, created);
    if (created) db.AccessRequests.Add(row);
    Audit(db, row, "access.approved", actor, correlation);
    return row;
  }
}
