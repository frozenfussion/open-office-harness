// SPDX-License-Identifier: AGPL-3.0-only
using System.Text.Json.Nodes;
using ControlCentre.Platform;
using ControlCentre.Rights;
using Microsoft.EntityFrameworkCore;

namespace ControlCentre.Registry;

public static class RegistryRoutes
{
  public static readonly string[] ModelFields = ["purpose", "role", "location", "api_type", "endpoint_url", "model_id", "rate_limit_per_minute", "daily_budget"];
  public static object View(ModelEntry m) => new { model_entry_id = m.Id, m.Purpose, m.Tier, m.Role, m.Location, m.ApiType, m.EndpointUrl, m.ModelId, m.SecretRef, m.RateLimitPerMinute, m.DailyBudget, m.Health, m.Title, has_key = m.ApiKeyEncrypted is not null, m.Priority, m.CreatedAt, m.InputPricePerMillion, m.OutputPricePerMillion, m.TimeoutSeconds, request_settings = JsonNode.Parse(m.RequestSettings) };
  public static void Map(WebApplication app)
  {
    app.MapGet("/api/models/{id}/key", async (string id, HttpContext c, CentreDb db, ModelKeys keys) =>
    {
      Api.Authorize(c, gateway: true); Api.Query(c);
      var row = await db.Models.FindAsync(Api.Id(id));
      Api.Found(row is { DeletedAt: null, ApiKeyEncrypted: not null });
      c.Response.Headers.CacheControl = "no-store";
      c.RequestServices.GetRequiredService<ILoggerFactory>().CreateLogger("ModelKeys").LogInformation("Model key read for entry {ModelEntryId}", row!.Id);
      return Results.Ok(new { api_key = keys.Decrypt(row!.Id, row.ApiKeyEncrypted!) });
    }).RequireAuthorization();
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
      Api.Authorize(c); Api.Query(c, "limit", "after");
      var query = db.Models.Where(x => x.DeletedAt == null);
      if (c.Request.Query.ContainsKey("after"))
      {
        var after = Api.Id(Api.Q(c, "after"));
        var cursor = await db.Models.FindAsync(after);
        Api.Found(cursor is not null);
        var purpose = cursor!.Purpose; var tier = cursor.Tier; var role = cursor.Role;
        query = query.Where(x => x.Purpose.CompareTo(purpose) > 0 || x.Purpose == purpose &&
          (tier != null && x.Tier == null || x.Tier > tier || x.Tier == tier &&
            (x.Role.CompareTo(role) > 0 || x.Role == role && x.Id.CompareTo(after) > 0)));
      }
      return Results.Ok((await query.OrderBy(x => x.Purpose).ThenBy(x => x.Tier).ThenBy(x => x.Role).ThenBy(x => x.Id).Take(Api.Limit(c)).ToListAsync()).Select(View));
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
    var b = await Api.Body(c, ModelFields, "tier", "secret_ref", "title", "api_key", "priority", "timeout_seconds", "input_price_per_million", "output_price_per_million", "request_settings");
    var row = id is null ? new ModelEntry() : await db.Models.FindAsync(id.Value);
    Api.Found(row is not null && row.DeletedAt == null);
    var before = id is null ? null : JsonNode.Parse(Api.Encode(View(row!)));
    var m = row!;
    m.Purpose = Api.String(b, "purpose");
    m.Tier = b.ContainsKey("tier") ? Api.Value<int>(b, "tier") : null;
    Api.Require(m.Purpose == "chat" ? m.Tier is > 0 : !b.ContainsKey("tier"));
    m.Role = Api.String(b, "role"); Api.Require(m.Role is "main" or "backup");
    m.Location = Api.String(b, "location"); Api.Require(m.Location is "on_prem" or "cloud");
    var oldType = m.ApiType; var oldEndpoint = m.EndpointUrl;
    var hadKey = m.ApiKeyEncrypted is not null;
    m.ApiType = Api.String(b, "api_type");
    m.EndpointUrl = Api.String(b, "endpoint_url");
    Api.Require(Uri.TryCreate(m.EndpointUrl, UriKind.Absolute, out var uri) && uri.Scheme is "http" or "https" && !string.IsNullOrEmpty(uri.Host) && string.IsNullOrEmpty(uri.UserInfo) && !m.EndpointUrl.Any(char.IsWhiteSpace));
    m.ModelId = Api.String(b, "model_id");
    m.SecretRef = b.ContainsKey("secret_ref") ? Api.Value<string>(b, "secret_ref") : m.SecretRef;
    Api.Require(m.SecretRef == "" || System.Text.RegularExpressions.Regex.IsMatch(m.SecretRef, "^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$") && m.SecretRef.Length <= 253, "secret_ref must name a Kubernetes Secret");
    m.RateLimitPerMinute = Api.Value<int>(b, "rate_limit_per_minute"); Api.Require(m.RateLimitPerMinute > 0);
    m.DailyBudget = Api.Value<decimal>(b, "daily_budget"); Api.Require(m.DailyBudget >= 0);
    m.Title = b.ContainsKey("title") ? Api.Value<string>(b, "title") : m.Title;
    m.Priority = b.ContainsKey("priority") ? Api.Value<int>(b, "priority") : m.Priority;
    m.TimeoutSeconds = b.ContainsKey("timeout_seconds") ? Api.Value<int>(b, "timeout_seconds") : m.TimeoutSeconds;
    m.InputPricePerMillion = b.ContainsKey("input_price_per_million") ? Api.Value<decimal>(b, "input_price_per_million") : m.InputPricePerMillion;
    m.OutputPricePerMillion = b.ContainsKey("output_price_per_million") ? Api.Value<decimal>(b, "output_price_per_million") : m.OutputPricePerMillion;
    Api.Require(m.Priority is >= 1 and <= 1000 && m.TimeoutSeconds is >= 10 and <= 900 && m.InputPricePerMillion >= 0 && m.OutputPricePerMillion >= 0);
    if (b.ContainsKey("request_settings"))
    {
      Api.Require(b["request_settings"] is JsonObject, "request_settings must be a JSON object");
      m.RequestSettings = b["request_settings"]!.ToJsonString();
    }
    string? keyChange = null;
    if (b.ContainsKey("api_key"))
    {
      var key = Api.Value<string>(b, "api_key");
      Api.Require(key.Length <= 4096);
      m.ApiKeyEncrypted = key.Length == 0 ? null : c.RequestServices.GetRequiredService<ModelKeys>().Encrypt(m.Id, key);
      keyChange = key.Length == 0 ? "removed" : hadKey ? "changed" : "set";
    }
    else if (hadKey && (oldType != m.ApiType || oldEndpoint != m.EndpointUrl))
    { m.ApiKeyEncrypted = null; keyChange = "removed"; }
    Api.Stamp(m, Api.Actor(c), id is null);
    if (id is null) db.Models.Add(m);
    if (m.Tier is not null) await RightsRoutes.EnsureRight(db, "chat.tier." + m.Tier, "tier", c);
    Api.Change(db, Api.Actor(c), id is null ? "model.created" : "model.updated", m.ModelId, Api.Correlation(c), new { before, after = View(m), api_key = keyChange });
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
