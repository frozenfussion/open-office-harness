// SPDX-License-Identifier: AGPL-3.0-only
using System.Globalization;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Nodes;
using ControlCentre.Registry;
using Microsoft.EntityFrameworkCore;

namespace ControlCentre.Platform;

public sealed class OperationsClient(HttpClient http, IConfiguration config, ModelConnection connection)
{
  public async Task<JsonNode?> Get(string setting, string path, CancellationToken ct)
  {
    using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct); timeout.CancelAfter(TimeSpan.FromSeconds(5));
    try
    {
      var token = await connection.Token(timeout.Token);
      if (token is null || string.IsNullOrEmpty(config[setting])) return null;
      using var request = new HttpRequestMessage(HttpMethod.Get, config[setting]!.TrimEnd('/') + path);
      request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
      using var response = await http.SendAsync(request, timeout.Token);
      return response.IsSuccessStatusCode ? await response.Content.ReadFromJsonAsync<JsonNode>(timeout.Token) : null;
    }
    catch (Exception e) when (e is HttpRequestException or OperationCanceledException or JsonException or InvalidOperationException) { return null; }
  }
}
public sealed record HealthRow(string Name, string Status, DateTimeOffset? CheckedAt);
public sealed class ServiceHealth
{
  public static readonly string[] Services = ["harness-api", "model-gateway", "slides-worker", "audit-writer", "cost-meter", "safety-watcher"];
  private HealthRow[] rows = Services.Concat(["kafka", "keycloak"]).Select(x => new HealthRow(x, "unknown", null)).ToArray();
  public HealthRow[] Rows => Volatile.Read(ref rows);
  public void Set(HealthRow[] value) => Volatile.Write(ref rows, value);
}
public sealed class HealthPoller(ServiceHealth state, HttpClient http, IConfiguration config, IKafka kafka, TimeProvider clock) : BackgroundService
{
  public async Task Refresh(CancellationToken ct)
  {
    async Task<HealthRow> Check(string name)
    {
      try
      {
        if (name == "kafka") return new(name, kafka.Healthy() ? "ok" : "down", clock.GetUtcNow());
        var setting = name == "model-gateway" ? "CC_GATEWAY_URL" : "CC_" + name.Replace('-', '_').ToUpperInvariant() + "_URL";
        var address = name == "keycloak" ? config["CC_OIDC_ISSUER"]?.TrimEnd('/') + "/.well-known/openid-configuration" : config[setting]?.TrimEnd('/') + "/health";
        if (string.IsNullOrEmpty(address) || !Uri.TryCreate(address, UriKind.Absolute, out _)) return new(name, "unknown", clock.GetUtcNow());
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct); timeout.CancelAfter(TimeSpan.FromSeconds(5));
        using var response = await http.GetAsync(address, timeout.Token);
        var body = response.IsSuccessStatusCode ? await response.Content.ReadFromJsonAsync<JsonObject>(timeout.Token) : null;
        var ok = name == "keycloak" ? body?["issuer"]?.ToString() == config["CC_OIDC_ISSUER"] : body?["status"]?.ToString() == "ok";
        return new(name, ok ? "ok" : "down", clock.GetUtcNow());
      }
      catch (Exception e) when (e is HttpRequestException or OperationCanceledException or JsonException or InvalidOperationException or Confluent.Kafka.KafkaException) { return new(name, "down", clock.GetUtcNow()); }
    }
    state.Set(await Task.WhenAll(ServiceHealth.Services.Concat(["kafka", "keycloak"]).Select(Check)));
  }
  protected override async Task ExecuteAsync(CancellationToken stoppingToken)
  {
    await Task.Yield();
    while (!stoppingToken.IsCancellationRequested)
    {
      await Refresh(stoppingToken);
      try { await Task.Delay(TimeSpan.FromSeconds(30), stoppingToken); } catch (OperationCanceledException) { break; }
    }
  }
}
public static class OperationsRoutes
{
  public static void Map(WebApplication app)
  {
    app.MapGet("/api/admin/health", (HttpContext c, ServiceHealth health) =>
    { Api.Authorize(c); Api.Query(c); return Results.Ok(health.Rows.Select(x => new JsonObject { ["name"] = x.Name, ["status"] = x.Status, ["checked_at"] = x.CheckedAt })); }).RequireAuthorization();
    app.MapGet("/api/admin/dead-letters/count", async (HttpContext c, CentreDb db) =>
    { Api.Authorize(c); Api.Query(c); return Results.Ok(new { count = await db.DeadLetters.CountAsync() }); }).RequireAuthorization();
    app.MapGet("/api/admin/dead-letters", async (HttpContext c, CentreDb db) =>
    {
      Api.Authorize(c); Api.Query(c, "topic", "before", "limit"); var limit = Api.Limit(c); var query = db.DeadLetters.AsQueryable();
      if (c.Request.Query.ContainsKey("topic")) { var topic = Api.Q(c, "topic"); Api.Require(DeadLetterConsumer.Topics.Contains(topic)); query = query.Where(x => x.Topic == topic); }
      if (c.Request.Query.ContainsKey("before"))
      {
        var parts = Api.Q(c, "before").Split(','); Api.Require(parts.Length == 2);
        Api.Require(DateTimeOffset.TryParse(parts[0], CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind, out var at) && at.Offset == TimeSpan.Zero);
        var id = Api.Id(parts[1]); query = query.Where(x => x.ReceivedAt < at || x.ReceivedAt == at && x.Id.CompareTo(id) < 0);
      }
      return Results.Ok(await query.OrderByDescending(x => x.ReceivedAt).ThenByDescending(x => x.Id).Take(limit).ToListAsync());
    }).RequireAuthorization();
    app.MapGet("/api/admin/trail", async (HttpContext c, OperationsClient client, CentreDb db) =>
    {
      Api.Authorize(c); Api.Query(c, "correlation_id", "user_id", "actor", "action", "before_id", "limit"); Api.Limit(c);
      if (c.Request.Query.ContainsKey("correlation_id")) Api.Id(Api.Q(c, "correlation_id"));
      if (c.Request.Query.ContainsKey("before_id")) Api.Require(long.TryParse(Api.Q(c, "before_id"), out var n) && n > 0);
      foreach (var key in new[] { "user_id", "actor", "action" }) if (c.Request.Query.ContainsKey(key)) Api.Q(c, key);
      var result = await client.Get("CC_AUDIT_WRITER_URL", "/v1/trail" + c.Request.QueryString, c.RequestAborted);
      if (result is not JsonArray rows) return Api.Error(503, "unavailable", "Audit trail unavailable");
      var users = rows.OfType<JsonObject>().Select(x => x["user_id"]?.GetValue<string>()).OfType<string>().Distinct().ToArray();
      var people = await db.People.AsNoTracking().Where(x => users.Contains(x.UserId) && x.DeletedAt == null).ToDictionaryAsync(x => x.UserId);
      var access = await db.AccessRequests.AsNoTracking().Where(x => users.Contains(x.UserId) && x.DeletedAt == null).ToDictionaryAsync(x => x.UserId);
      foreach (var row in rows.OfType<JsonObject>())
      {
        if (row["user_id"] is not JsonValue userValue || !userValue.TryGetValue<string>(out var user)) continue;
        people.TryGetValue(user, out var person); access.TryGetValue(user, out var request);
        row["person"] = new[] { person?.Name, request?.Name, person?.Email, request?.Email }.FirstOrDefault(x => !string.IsNullOrWhiteSpace(x)) ?? user;
      }
      return Results.Ok(rows);
    }).RequireAuthorization();
    app.MapGet("/api/admin/overview", async (HttpContext c, CentreDb db, OperationsClient client, ServiceHealth health, TimeProvider clock, DisplayCalendar calendar) =>
    {
      Api.Authorize(c); Api.Query(c); var now = clock.GetUtcNow(); var day = now.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
      var countsTask = client.Get("CC_AUDIT_WRITER_URL", "/v1/counts?day=" + day, c.RequestAborted);
      var costTask = client.Get("CC_COST_METER_URL", "/v1/costs?day=" + day, c.RequestAborted);
      await Task.WhenAll(countsTask, costTask);
      var counts = countsTask.Result as JsonObject; var cost = costTask.Result as JsonObject;
      long? Count(string key) => counts?["by_action"] is JsonObject actions ? actions[key] is JsonValue v && v.TryGetValue<long>(out var n) && n >= 0 ? n : 0 : null;
      var attention = new List<object>();
      var visible = db.AccessRequests.Where(x => !x.IsServiceAccount && !x.UserId.StartsWith("stage-check-") && !x.UserId.StartsWith("service-account-") && !db.People.Any(p => p.UserId == x.UserId && p.IsServiceAccount));
      foreach (var row in await visible.Where(x => x.DeletedAt == null && x.Status == "pending").ToListAsync())
        attention.Add(new { kind = "access_request", title = "Access request", detail = row.Name ?? row.UserId, at = row.RequestedAt, link = "#approvals" });
      foreach (var row in await db.TierRequests.Where(x => x.DeletedAt == null && x.Status == "pending" && visible.Any(a => a.UserId == x.UserId)).ToListAsync())
        attention.Add(new { kind = "tier_request", title = "Model request", detail = "Tier " + row.Tier, at = row.RequestedAt, link = "#approvals" });
      foreach (var row in await db.SkillRequests.Where(x => x.DeletedAt == null && x.Status == "pending" && visible.Any(a => a.UserId == x.UserId)).ToListAsync())
        attention.Add(new { kind = "skill_request", title = "Skill request", detail = row.Skill, at = row.RequestedAt, link = "#approvals" });
      foreach (var row in await db.Approvals.Where(x => x.DeletedAt == null && x.Status == "pending" && !x.RequesterUserId.StartsWith("stage-check-") && !x.RequesterUserId.StartsWith("service-account-") && !db.People.Any(p => p.UserId == x.RequesterUserId && p.IsServiceAccount) && !db.AccessRequests.Any(a => a.UserId == x.RequesterUserId && a.IsServiceAccount)).ToListAsync())
        attention.Add(new { kind = "approval", title = row.Action == "safety.flag" ? "Safety flag" : "Job approval", detail = row.Action, at = row.CreatedAt, link = "#approvals" });
      foreach (var row in await db.Models.Where(x => x.DeletedAt == null && x.Health == "down").ToListAsync())
        attention.Add(new { kind = "model_down", title = "Model down", detail = row.Title, at = row.HealthChangedAt ?? row.CreatedAt, link = "#models" });
      var since = now.AddHours(-24); var recentDead = db.DeadLetters.Where(x => x.ReceivedAt >= since); var dead = await recentDead.CountAsync();
      if (dead > 0) attention.Add(new { kind = "dead_letter", title = "Failed messages", detail = dead + " in the last 24 hours", at = await recentDead.MaxAsync(x => x.ReceivedAt), link = "#overview" });
      var (start, end) = calendar.Day(now);
      var activePeople = await db.People.CountAsync(x => x.DeletedAt == null && !x.IsServiceAccount && !x.UserId.StartsWith("stage-check-") && !x.UserId.StartsWith("service-account-") && !x.UserId.StartsWith("admin-test-") && !x.UserId.StartsWith("title-") && x.LastSeenAt >= start && x.LastSeenAt < end && db.AccessRequests.Any(a => a.UserId == x.UserId && a.DeletedAt == null && a.Status == "approved"));
      return Results.Ok(new JsonObject
      {
        ["people_active_today"] = activePeople,
        ["people_approved"] = await visible.CountAsync(x => x.DeletedAt == null && x.Status == "approved"),
        ["skill_jobs_today"] = Count("skill.requested"),
        ["model_calls_today"] = Count("model.call") + Count("model.classify"),
        ["cost_today_usd"] = cost?["total_usd"]?.DeepClone(),
        ["needs_attention"] = JsonSerializer.SerializeToNode(attention, Api.Json),
        ["health"] = JsonSerializer.SerializeToNode(health.Rows.Select(x => new JsonObject { ["name"] = x.Name, ["status"] = x.Status, ["checked_at"] = x.CheckedAt }), Api.Json)
      });
    }).RequireAuthorization();
  }
}
