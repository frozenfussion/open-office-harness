// SPDX-License-Identifier: AGPL-3.0-only
using System.Text.Json.Nodes;
using ControlCentre.Platform;
using ControlCentre.Rights;
using Microsoft.EntityFrameworkCore;

namespace ControlCentre.Registry;

public static class RegistryRoutes
{
  public static readonly string[] ModelFields = ["purpose", "role", "location", "api_type", "endpoint_url", "model_id", "secret_ref", "rate_limit_per_minute", "daily_budget"];
  public static object View(ModelEntry m) => new { model_entry_id = m.Id, m.Purpose, m.Tier, m.Role, m.Location, m.ApiType, m.EndpointUrl, m.ModelId, m.SecretRef, m.RateLimitPerMinute, m.DailyBudget, m.Health };
  public static void Map(WebApplication app)
  {
    app.MapGet("/api/models", async (HttpContext c, CentreDb db) =>
    {
      Api.Authorize(c, gateway: true); Api.Query(c, "purpose", "tier");
      var purpose = Api.Q(c, "purpose");
      int? tier = null;
      if (purpose == "chat")
      {
        Api.Require(int.TryParse(Api.Q(c, "tier"), out var n) && n > 0);
        tier = n;
      }
      else Api.Require(!c.Request.Query.ContainsKey("tier"));
      var rows = await db.Models.Where(x => x.DeletedAt == null && x.Purpose == purpose && x.Tier == tier).OrderBy(x => x.Role).ToListAsync();
      return Results.Ok(rows.Select(View));
    }).RequireAuthorization();
    app.MapGet("/api/admin/models", async (HttpContext c, CentreDb db) =>
    {
      Api.Authorize(c); Api.Query(c, "limit");
      return Results.Ok((await db.Models.Where(x => x.DeletedAt == null).OrderBy(x => x.Id).Take(Api.Limit(c)).ToListAsync()).Select(View));
    }).RequireAuthorization();
    app.MapGet("/api/admin/models/{id}", async (string id, HttpContext c, CentreDb db) =>
    {
      Api.Authorize(c); Api.Query(c);
      var row = await db.Models.FindAsync(Api.Id(id));
      Api.Found(row is not null && row.DeletedAt == null);
      return Results.Ok(View(row!));
    }).RequireAuthorization();
    app.MapPost("/api/admin/models", async (HttpContext c, CentreDb db) => await SaveModel(c, db, null)).RequireAuthorization();
    app.MapPut("/api/admin/models/{id}", async (string id, HttpContext c, CentreDb db) => { Api.Authorize(c); return await SaveModel(c, db, Api.Id(id)); }).RequireAuthorization();
    app.MapDelete("/api/admin/models/{id}", async (string id, HttpContext c, CentreDb db) =>
    {
      Api.Authorize(c); Api.Query(c);
      var row = await db.Models.FindAsync(Api.Id(id));
      await Api.Remove(c, db, row, row?.ModelId ?? id);
      return Results.Ok(new { status = "removed" });
    }).RequireAuthorization();
    app.MapGet("/api/admin/skills", async (HttpContext c, CentreDb db) =>
    {
      Api.Authorize(c); Api.Query(c, "limit");
      return Results.Ok((await db.Skills.Where(x => x.DeletedAt == null).OrderBy(x => x.Name).Take(Api.Limit(c)).ToListAsync()).Select(x => JsonNode.Parse(x.Manifest)));
    }).RequireAuthorization();
    app.MapGet("/api/admin/skills/{name}", async (string name, HttpContext c, CentreDb db) =>
    {
      Api.Authorize(c); Api.Query(c); Api.Text(name);
      var skill = await db.Skills.SingleOrDefaultAsync(x => x.Name == name && x.DeletedAt == null);
      Api.Found(skill is not null);
      return Results.Ok(JsonNode.Parse(skill!.Manifest));
    }).RequireAuthorization();
    app.MapPost("/api/admin/skills", async (HttpContext c, CentreDb db, SchemaChecks schemas) => await SaveSkill(c, db, schemas, null)).RequireAuthorization();
    app.MapPut("/api/admin/skills/{name}", async (string name, HttpContext c, CentreDb db, SchemaChecks schemas) => await SaveSkill(c, db, schemas, name)).RequireAuthorization();
    app.MapDelete("/api/admin/skills/{name}", async (string name, HttpContext c, CentreDb db) =>
    {
      Api.Authorize(c); Api.Query(c); Api.Text(name);
      await Api.Remove(c, db, await db.Skills.SingleOrDefaultAsync(x => x.Name == name), name);
      return Results.Ok(new { status = "removed" });
    }).RequireAuthorization();
  }
  private static async Task<IResult> SaveModel(HttpContext c, CentreDb db, Guid? id)
  {
    Api.Authorize(c); Api.Query(c);
    var b = await Api.Body(c, ModelFields, "tier");
    var row = id is null ? new ModelEntry() : await db.Models.FindAsync(id.Value);
    Api.Found(row is not null && row.DeletedAt == null);
    var before = id is null ? null : JsonNode.Parse(Api.Encode(View(row!)));
    var m = row!;
    m.Purpose = Api.String(b, "purpose");
    m.Tier = b.ContainsKey("tier") ? Api.Value<int>(b, "tier") : null;
    Api.Require(m.Purpose == "chat" ? m.Tier is > 0 : !b.ContainsKey("tier"));
    m.Role = Api.String(b, "role"); Api.Require(m.Role is "main" or "backup");
    m.Location = Api.String(b, "location"); Api.Require(m.Location is "on_prem" or "cloud");
    m.ApiType = Api.String(b, "api_type");
    m.EndpointUrl = Api.String(b, "endpoint_url");
    Api.Require(Uri.TryCreate(m.EndpointUrl, UriKind.Absolute, out var uri) && uri.Scheme is "http" or "https" && !string.IsNullOrEmpty(uri.Host) && string.IsNullOrEmpty(uri.UserInfo) && !m.EndpointUrl.Any(char.IsWhiteSpace));
    m.ModelId = Api.String(b, "model_id");
    m.SecretRef = Api.String(b, "secret_ref");
    Api.Require(System.Text.RegularExpressions.Regex.IsMatch(m.SecretRef, "^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$") && m.SecretRef.Length <= 253, "secret_ref must name a Kubernetes Secret");
    m.RateLimitPerMinute = Api.Value<int>(b, "rate_limit_per_minute"); Api.Require(m.RateLimitPerMinute > 0);
    m.DailyBudget = Api.Value<decimal>(b, "daily_budget"); Api.Require(m.DailyBudget >= 0);
    Api.Stamp(m, Api.Actor(c), id is null);
    if (id is null) db.Models.Add(m);
    if (m.Tier is not null) await RightsRoutes.EnsureRight(db, "chat.tier." + m.Tier, "tier", c);
    Api.Change(db, Api.Actor(c), id is null ? "model.created" : "model.updated", m.ModelId, Api.Correlation(c), new { before, after = View(m) });
    await db.SaveChangesAsync();
    return Results.Json(View(m), statusCode: id is null ? 201 : 200);
  }
  private static async Task<IResult> SaveSkill(HttpContext c, CentreDb db, SchemaChecks schemas, string? name)
  {
    Api.Authorize(c); Api.Query(c);
    var b = await Api.Body(c, ["name", "title", "kind", "description", "input_schema", "output_schema", "right", "needs_approval", "version"], "topic");
    Api.Require(schemas.Manifest(b), "Invalid skill manifest");
    var skillName = Api.String(b, "name");
    Api.Require(name is null || name == skillName, "Skill name must match path");
    var existing = await db.Skills.SingleOrDefaultAsync(x => x.Name == skillName);
    if (name is not null) Api.Found(existing is not null && existing.DeletedAt == null);
    if (name is null && existing is { DeletedAt: null } && existing.Version == Api.String(b, "version")) return Results.Ok(JsonNode.Parse(existing.Manifest));
    if (name is null && existing is { DeletedAt: null }) throw new ApiException(409, "conflict", "Skill exists; use PUT to update");
    var row = existing ?? new Skill { Name = skillName };
    var before = existing is null ? null : JsonNode.Parse(row.Manifest);
    row.Version = Api.String(b, "version");
    row.Manifest = b.ToJsonString();
    row.DeletedAt = null;
    Api.Stamp(row, Api.Actor(c), existing is null);
    if (existing is null) db.Skills.Add(row);
    await RightsRoutes.EnsureRight(db, Api.String(b, "right"), "skill", c);
    Api.Change(db, Api.Actor(c), name is null ? "skill.registered" : "skill.updated", skillName, Api.Correlation(c), new { before, after = b });
    await db.SaveChangesAsync();
    return Results.Json(b, statusCode: name is null ? 201 : 200);
  }
}
