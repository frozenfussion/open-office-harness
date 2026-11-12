// SPDX-License-Identifier: AGPL-3.0-only
using System.Globalization;
using System.Text.Json.Nodes;
using ControlCentre.Platform;
using ControlCentre.Access;
using ControlCentre.Registry;
using Microsoft.EntityFrameworkCore;

namespace ControlCentre.Rights;

public static class RightsRoutes
{
  public static async Task<string> Decision(CentreDb db, string userId, string key)
  {
    if (!await AccessPolicy.Approved(db, userId)) return "no-grant";
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
      if (!await AccessPolicy.Approved(db, user)) return Results.Ok(new { chat_tiers = Array.Empty<int>(), chat_tier_titles = new Dictionary<string, string>(), chat_tier_thinking_switch = new Dictionary<string, bool>(), requestable_tiers = Array.Empty<RequestableTier>(), requestable_skills = Array.Empty<RequestableSkill>(), skills = Array.Empty<string>(), image = false });
      var keys = await db.Grants.Where(x => x.DeletedAt == null && (x.SubjectType == "everyone" || x.SubjectId == user))
              .Select(x => x.RightKey).Distinct().ToListAsync();
      var active = await db.Rights.Where(x => x.DeletedAt == null && keys.Contains(x.Key)).Select(x => x.Key).ToListAsync();
      var tiers = active.Where(x => x.StartsWith("chat.tier.", StringComparison.Ordinal)).Select(x => int.Parse(x[10..], CultureInfo.InvariantCulture)).Order().ToArray();
      var skills = (await db.Skills.Where(x => x.DeletedAt == null).ToListAsync()).Where(x => active.Contains(JsonNode.Parse(x.Manifest)!["right"]!.GetValue<string>())).Select(x => x.Name).Order().ToArray();
      var mainEntries = await TierChoices.MainEntries(db);
      var allowedMain = mainEntries.Where(x => tiers.Contains(x.Tier)).ToList();
      var titles = allowedMain.ToDictionary(x => x.Tier.ToString(CultureInfo.InvariantCulture), x => x.Title);
      var switches = allowedMain.ToDictionary(x => x.Tier.ToString(CultureInfo.InvariantCulture), x => x.ThinkingSwitch);
      var requestable = await TierChoices.Requestable(db, user, mainEntries);
      return Results.Ok(new { chat_tiers = tiers, chat_tier_titles = titles, chat_tier_thinking_switch = switches, requestable_skills = (await SkillChoices.Requestable(db, user)).Select(SkillChoices.View), requestable_tiers = requestable.Select(x => new System.Text.Json.Nodes.JsonObject { ["tier"] = x.Tier, ["title"] = x.Title, ["requested"] = x.Requested }), skills, image = active.Contains("image.generate") });
    }).RequireAuthorization();
    app.MapGet("/api/skills", async (HttpContext c, CentreDb db) =>
    {
      Api.Query(c, "user_id");
      var user = Api.Q(c, "user_id");
      Api.Authorize(c, user);
      var result = new List<JsonNode>();
      if (!await AccessPolicy.Approved(db, user)) return Results.Ok(result);
      foreach (var skill in await db.Skills.Where(x => x.DeletedAt == null).ToListAsync())
      {
        var manifest = JsonNode.Parse(skill.Manifest)!;
        if (await Decision(db, user, manifest["right"]!.GetValue<string>()) != "no-grant") result.Add(manifest);
      }
      return Results.Ok(result);
    }).RequireAuthorization();
    app.MapGet("/api/admin/rights", async (HttpContext c, CentreDb db) =>
    {
      Api.Authorize(c); Api.Query(c, "limit", "after");
      var query = db.Rights.AsQueryable();
      if (c.Request.Query.ContainsKey("after"))
      {
        var after = Api.Q(c, "after");
        query = query.Where(x => x.Key.CompareTo(after) > 0);
      }
      return Results.Ok(await query.OrderBy(x => x.Key).Take(Api.Limit(c)).ToListAsync());
    }).RequireAuthorization();
    app.MapGet("/api/admin/people", async (HttpContext c, CentreDb db) =>
    {
      Api.Authorize(c); Api.Query(c, "limit", "after");
      var query = db.People.Where(x => x.DeletedAt == null && !x.IsServiceAccount && !x.UserId.StartsWith("stage-check-") && !x.UserId.StartsWith("service-account-"));
      if (c.Request.Query.ContainsKey("after"))
      {
        var after = Api.Q(c, "after");
        query = query.Where(x => x.UserId.CompareTo(after) > 0);
      }
      var result = new List<object>();
      foreach (var person in await query.OrderBy(x => x.UserId).Take(Api.Limit(c)).ToListAsync())
        result.Add(await PersonView(db, person));
      return Results.Ok(result);
    }).RequireAuthorization();
    app.MapGet("/api/admin/people/{user_id}", async (string user_id, HttpContext c, CentreDb db) =>
    {
      Api.Authorize(c); Api.Query(c); Api.Text(user_id);
      var person = await db.People.SingleOrDefaultAsync(x => x.UserId == user_id && x.DeletedAt == null && !x.IsServiceAccount && !x.UserId.StartsWith("stage-check-") && !x.UserId.StartsWith("service-account-"));
      Api.Found(person is not null);
      return Results.Ok(await PersonView(db, person!));
    }).RequireAuthorization();
    app.MapGet("/api/admin/grants", async (HttpContext c, CentreDb db) =>
    {
      Api.Authorize(c); Api.Query(c, "right_key", "limit", "after");
      var query = db.Grants.Where(x => x.DeletedAt == null);
      if (c.Request.Query.ContainsKey("right_key"))
      { var key = Api.Q(c, "right_key"); query = query.Where(x => x.RightKey == key); }
      if (c.Request.Query.ContainsKey("after"))
      { var after = Api.Id(Api.Q(c, "after")); query = query.Where(x => x.Id.CompareTo(after) > 0); }
      return Results.Ok(await query.OrderBy(x => x.Id).Take(Api.Limit(c)).ToListAsync());
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
      await using var transaction = await db.Database.BeginTransactionAsync();
      await AccessPolicy.Lock(db);
      if (subject is not null)
      {
        await People.Ensure(db, subject, Api.Actor(c), Api.Correlation(c));
        int? tier = key.StartsWith("chat.tier.", StringComparison.Ordinal) && int.TryParse(key[10..], out var number) ? number : null;
        await AccessPolicy.Approve(db, subject, Api.Actor(c), Api.Actor(c), Api.Correlation(c), tier);
        var existing = await db.Grants.SingleOrDefaultAsync(x => x.RightKey == key && x.SubjectType == "user" && x.SubjectId == subject && x.DeletedAt == null);
        if (existing is not null)
        { await db.SaveChangesAsync(); await transaction.CommitAsync(); return Results.Ok(existing); }
      }
      var row = new Grant { RightKey = key, SubjectType = type, SubjectId = subject };
      Api.Stamp(row, Api.Actor(c), true);
      db.Grants.Add(row);
      Api.Change(db, Api.Actor(c), "grant.created", key, Api.Correlation(c), new { after = row });
      await db.SaveChangesAsync();
      await transaction.CommitAsync();
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
    email = person.Email ?? (await db.AccessRequests.SingleOrDefaultAsync(x => x.UserId == person.UserId))?.Email,
    name = person.Name ?? (await db.AccessRequests.SingleOrDefaultAsync(x => x.UserId == person.UserId))?.Name,
    person.FirstSeenAt,
    person.LastSeenAt,
    grants = await db.Grants.Where(x => x.DeletedAt == null && (x.SubjectType == "everyone" || x.SubjectId == person.UserId)).ToListAsync()
  };
}
