// SPDX-License-Identifier: AGPL-3.0-only
using System.Globalization;
using System.Text.Json.Nodes;
using ControlCentre.Platform;
using Microsoft.EntityFrameworkCore;

namespace ControlCentre.Rights;

public static class RightsRoutes
{
  public static async Task<string> Decision(CentreDb db, string userId, string key)
  {
    if (!await db.Rights.AnyAsync(x => x.Key == key && x.DeletedAt == null)) return "no-grant";
    var grants = db.Grants.Where(x => x.DeletedAt == null && x.RightKey == key);
    if (await grants.AnyAsync(x => x.SubjectType == "user" && x.SubjectId == userId)) return "grant:user";
    return await grants.AnyAsync(x => x.SubjectType == "everyone") ? "grant:everyone" : "no-grant";
  }
  public static async Task EnsureRight(CentreDb db, string key, string source, HttpContext c)
  {
    if (await db.Rights.AnyAsync(x => x.Key == key)) return;
    var right = new Right { Key = key, Description = key, Source = source };
    Api.Stamp(right, Api.Actor(c), true);
    db.Rights.Add(right);
    Api.Change(db, Api.Actor(c), "right.created", key, Api.Correlation(c), new { after = right });
  }
  public static void Map(WebApplication app)
  {
    app.MapPost("/api/rights/check", async (HttpContext c, CentreDb db) =>
    {
      Api.Query(c);
      var body = await Api.Body(c, ["user_id", "action", "target"]);
      var user = Api.String(body, "user_id");
      Api.Authorize(c, user);
      var action = Api.String(body, "action");
      var target = Api.String(body, "target");
      string key;
      switch (action)
      {
        case "chat.tier":
          Api.Require(int.TryParse(target, NumberStyles.None, CultureInfo.InvariantCulture, out var tier) && tier > 0, "Tier must be a positive integer");
          key = "chat.tier." + tier.ToString(CultureInfo.InvariantCulture);
          break;
        case "skill.use":
          var skill = await db.Skills.SingleOrDefaultAsync(x => x.Name == target && x.DeletedAt == null);
          key = skill is null ? "" : JsonNode.Parse(skill.Manifest)!["right"]!.GetValue<string>();
          break;
        case "image.generate": key = action; break;
        default: throw new ApiException(400, "invalid_input", "Unknown action");
      }
      var decision = await Decision(db, user, key);
      return Results.Ok(new { allowed = decision != "no-grant", reason = decision == "no-grant" ? "No active grant" : "Active grant", decided_by = decision });
    }).RequireAuthorization();
    app.MapGet("/api/rights/me", async (HttpContext c, CentreDb db) =>
    {
      Api.Query(c, "user_id");
      var user = Api.Q(c, "user_id");
      Api.Authorize(c, user);
      var keys = await db.Grants.Where(x => x.DeletedAt == null && (x.SubjectType == "everyone" || x.SubjectId == user))
              .Select(x => x.RightKey).Distinct().ToListAsync();
      var active = await db.Rights.Where(x => x.DeletedAt == null && keys.Contains(x.Key)).Select(x => x.Key).ToListAsync();
      var tiers = active.Where(x => x.StartsWith("chat.tier.", StringComparison.Ordinal)).Select(x => int.Parse(x[10..], CultureInfo.InvariantCulture)).Order().ToArray();
      var skills = (await db.Skills.Where(x => x.DeletedAt == null).ToListAsync()).Where(x => active.Contains(JsonNode.Parse(x.Manifest)!["right"]!.GetValue<string>())).Select(x => x.Name).Order().ToArray();
      return Results.Ok(new { chat_tiers = tiers, skills, image = active.Contains("image.generate") });
    }).RequireAuthorization();
    app.MapGet("/api/skills", async (HttpContext c, CentreDb db) =>
    {
      Api.Query(c, "user_id");
      var user = Api.Q(c, "user_id");
      Api.Authorize(c, user);
      var result = new List<JsonNode>();
      foreach (var skill in await db.Skills.Where(x => x.DeletedAt == null).ToListAsync())
      {
        var manifest = JsonNode.Parse(skill.Manifest)!;
        if (await Decision(db, user, manifest["right"]!.GetValue<string>()) != "no-grant") result.Add(manifest);
      }
      return Results.Ok(result);
    }).RequireAuthorization();
    app.MapGet("/api/admin/rights", async (HttpContext c, CentreDb db) =>
    {
      Api.Authorize(c); Api.Query(c, "limit");
      return Results.Ok(await db.Rights.OrderBy(x => x.Key).Take(Api.Limit(c)).ToListAsync());
    }).RequireAuthorization();
    app.MapGet("/api/admin/people", async (HttpContext c, CentreDb db) =>
    {
      Api.Authorize(c); Api.Query(c, "limit");
      var result = new List<object>();
      foreach (var person in await db.People.Where(x => x.DeletedAt == null).OrderBy(x => x.UserId).Take(Api.Limit(c)).ToListAsync())
        result.Add(await PersonView(db, person));
      return Results.Ok(result);
    }).RequireAuthorization();
    app.MapGet("/api/admin/people/{user_id}", async (string user_id, HttpContext c, CentreDb db) =>
    {
      Api.Authorize(c); Api.Query(c); Api.Text(user_id);
      var person = await db.People.SingleOrDefaultAsync(x => x.UserId == user_id && x.DeletedAt == null);
      Api.Found(person is not null);
      return Results.Ok(await PersonView(db, person!));
    }).RequireAuthorization();
    app.MapPost("/api/admin/grants", async (HttpContext c, CentreDb db) =>
    {
      Api.Authorize(c); Api.Query(c);
      var b = await Api.Body(c, ["right_key", "subject_type"], "subject_id");
      var key = Api.String(b, "right_key");
      var type = Api.String(b, "subject_type");
      Api.Require(type is "user" or "everyone");
      var subject = type == "user" ? Api.String(b, "subject_id") : null;
      Api.Require(type != "everyone" || b["subject_id"] is null);
      Api.Require(await db.Rights.AnyAsync(x => x.Key == key && x.DeletedAt == null), "Unknown right");
      if (subject is not null)
      {
        var person = await Api.Person(db, subject, Api.Actor(c));
        if (db.Entry(person).State == EntityState.Added)
          Api.Change(db, Api.Actor(c), "person.created", subject, Api.Correlation(c), new { after = person });
      }
      var row = new Grant { RightKey = key, SubjectType = type, SubjectId = subject };
      Api.Stamp(row, Api.Actor(c), true);
      db.Grants.Add(row);
      Api.Change(db, Api.Actor(c), "grant.created", key, Api.Correlation(c), new { after = row });
      await db.SaveChangesAsync();
      return Results.Json(row, statusCode: 201);
    }).RequireAuthorization();
    app.MapDelete("/api/admin/grants/{id}", async (string id, HttpContext c, CentreDb db) =>
    {
      Api.Authorize(c); Api.Query(c);
      var key = Api.Id(id);
      var row = await db.Grants.FindAsync(key);
      await Api.Remove(c, db, row, row?.RightKey ?? id);
      return Results.Ok(new { status = "removed" });
    }).RequireAuthorization();
  }
  private static async Task<object> PersonView(CentreDb db, Person person) => new
  {
    person.Id,
    person.UserId,
    person.Email,
    person.Name,
    person.FirstSeenAt,
    person.LastSeenAt,
    grants = await db.Grants.Where(x => x.DeletedAt == null && (x.SubjectType == "everyone" || x.SubjectId == person.UserId)).ToListAsync()
  };
}
