// SPDX-License-Identifier: AGPL-3.0-only
using Microsoft.EntityFrameworkCore;
using ControlCentre.Access;

namespace ControlCentre.Platform;

public static class People
{
  public static async Task Observe(HttpContext context, CentreDb db, DisplayCalendar? calendar = null, TimeProvider? clock = null)
  {
    var actor = Api.Actor(context);
    var email = context.User.FindFirst("email")?.Value;
    var name = context.User.FindFirst("name")?.Value;
    var service = context.User.HasClaim(x => x.Type == "client_id") || context.User.FindFirst("preferred_username")?.Value.StartsWith("service-account-", StringComparison.Ordinal) == true;
    var now = (clock ?? TimeProvider.System).GetUtcNow();
    calendar ??= new DisplayCalendar();
    var current = await db.People.AsNoTracking().SingleOrDefaultAsync(x => x.UserId == actor);
    if (current is not null && current.IsServiceAccount == service && current.Email == email && current.Name == name && !calendar.RefreshSighting(current.LastSeenAt, now) && (!Api.Admin(context.User) || await AccessPolicy.Approved(db, actor))) return;

    await using var transaction = await db.Database.BeginTransactionAsync();
    AccessRequest? access = null;
    if (Api.Admin(context.User))
    {
      await AccessPolicy.Lock(db);
      access = await AccessPolicy.Approve(db, actor, actor, "system:admin-role", Api.Correlation(context));
    }
    var (person, created) = await Ensure(db, actor, actor, Api.Correlation(context), email, name);
    if (!created && (person.Email != email || person.Name != name))
    {
      var before = System.Text.Json.Nodes.JsonNode.Parse(Api.Encode(person));
      person.Email = email;
      person.Name = name;
      Api.Stamp(person, actor);
      Api.Change(db, actor, "person.updated", actor, Api.Correlation(context), new { before, after = person });
    }
    person.IsServiceAccount = service;
    access ??= await db.AccessRequests.SingleOrDefaultAsync(x => x.UserId == actor);
    if (access is not null) access.IsServiceAccount = service;
    // Count the first visit after local midnight even inside the hourly sighting throttle.
    if (created || calendar.RefreshSighting(person.LastSeenAt, now)) person.LastSeenAt = now;
    await db.SaveChangesAsync();
    await transaction.CommitAsync();
  }

  public static async Task<(Person Person, bool Created)> Ensure(CentreDb db, string userId, string actor, Guid correlation, string? email = null, string? name = null)
  {
    if (db.Database.CurrentTransaction is null) throw new InvalidOperationException("Person creation requires a transaction");
    var candidate = new Person { UserId = userId, Email = email, Name = name };
    Api.Stamp(candidate, actor, true);
    var inserted = await db.Database.ExecuteSqlInterpolatedAsync($"""
      INSERT INTO people (id, user_id, email, name, first_seen_at, last_seen_at, created_at, updated_at, created_by, updated_by)
      VALUES ({candidate.Id}, {userId}, {email}, {name}, {candidate.FirstSeenAt}, {candidate.LastSeenAt}, {candidate.CreatedAt}, {candidate.UpdatedAt}, {actor}, {actor})
      ON CONFLICT (user_id) DO NOTHING
      """);
    // The row lock also prevents simultaneous profile changes from duplicating their audit record.
    var person = (await db.People.FromSqlInterpolated($"SELECT * FROM people WHERE user_id = {userId} FOR UPDATE").ToListAsync()).Single();
    if (inserted == 1) Api.Change(db, actor, "person.created", userId, correlation, new { after = person });
    return (person, inserted == 1);
  }
}
