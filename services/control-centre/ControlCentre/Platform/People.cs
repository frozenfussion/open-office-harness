// SPDX-License-Identifier: AGPL-3.0-only
using Microsoft.EntityFrameworkCore;

namespace ControlCentre.Platform;

public static class People
{
  public static async Task Observe(HttpContext context, CentreDb db)
  {
    var actor = Api.Actor(context);
    var email = context.User.FindFirst("email")?.Value;
    var name = context.User.FindFirst("name")?.Value;
    var now = DateTimeOffset.UtcNow;
    var current = await db.People.AsNoTracking().SingleOrDefaultAsync(x => x.UserId == actor);
    if (current is not null && current.Email == email && current.Name == name && current.LastSeenAt > now.AddHours(-1)) return;

    await using var transaction = await db.Database.BeginTransactionAsync();
    var (person, created) = await Ensure(db, actor, actor, Api.Correlation(context), email, name);
    if (!created && (person.Email != email || person.Name != name))
    {
      var before = System.Text.Json.Nodes.JsonNode.Parse(Api.Encode(person));
      person.Email = email;
      person.Name = name;
      Api.Stamp(person, actor);
      Api.Change(db, actor, "person.updated", actor, Api.Correlation(context), new { before, after = person });
    }
    // A sighting is a system timestamp, refreshed at most hourly without a business audit event.
    if (person.LastSeenAt <= now.AddHours(-1)) person.LastSeenAt = now;
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
