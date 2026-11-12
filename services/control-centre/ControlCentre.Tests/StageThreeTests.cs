// SPDX-License-Identifier: AGPL-3.0-only
using System.Net;
using System.Net.Http.Json;
using System.Security.Claims;
using System.Text.Json.Nodes;
using Confluent.Kafka;
using ControlCentre.Platform;
using ControlCentre.Registry;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Xunit;

namespace ControlCentre.Tests;

public sealed class StageThreeTests
{
  private static CentreDb Database(bool owner = false) => new(new DbContextOptionsBuilder<CentreDb>().UseNpgsql(DatabaseConnections.Configure(TestSettings.Load()[owner ? "CC_TEST_DB_MIGRATE_CONNECTION" : "CC_TEST_DB_CONNECTION"])).Options);
  private static async Task Migrate() { await using var db = Database(true); await db.Database.MigrateAsync(); }
  private static async Task<JsonObject> Object(Task<HttpResponseMessage> task, HttpStatusCode status = HttpStatusCode.OK)
  { var response = await task; Assert.Equal(status, response.StatusCode); return (await response.Content.ReadFromJsonAsync<JsonObject>())!; }
  private static async Task Code(Task<HttpResponseMessage> task, HttpStatusCode status, string code) => Assert.Equal(code, (await Object(task, status))["code"]!.GetValue<string>());
  private static async Task<Skill> Skill(CentreDb db)
  {
    var name = "synthetic-" + Guid.NewGuid().ToString("N");
    var manifest = RoutesWithoutDatabaseTests.ValidManifest(name);
    var skill = new Skill { Name = name, Version = "1.0.0", Manifest = manifest.ToJsonString() };
    db.Skills.Add(skill); db.Rights.Add(new Right { Key = manifest["right"]!.GetValue<string>(), Source = "skill" }); await db.SaveChangesAsync(); return skill;
  }
  [DatabaseFact]
  public async Task SkillRequestsValidateEligibilityCallerReasonAndPrivacyAndApproveGrant()
  {
    await Migrate(); using var host = new Host(true); using var admin = host.Client(); using var harness = host.Client("harness");
    await using var db = Database(); var skill = await Skill(db); var user = "synthetic-" + Guid.NewGuid();
    Task<HttpResponseMessage> Request(string? reason = null) => harness.PostAsJsonAsync("/api/skill-requests", new { user_id = user, skill = skill.Name, reason });
    await Code(Request(), HttpStatusCode.Forbidden, "not_approved");
    db.AccessRequests.Add(new AccessRequest { UserId = user, Status = "approved" }); await db.SaveChangesAsync();
    await Code(Request(new string('x', 301)), HttpStatusCode.BadRequest, "invalid_input");
    await Code(harness.PostAsJsonAsync("/api/skill-requests", new { user_id = user, skill = "absent" }), HttpStatusCode.BadRequest, "skill_not_requestable");
    var reason = "Synthetic private reason";
    var responses = await Task.WhenAll(Request(reason), Request(reason)); Assert.Equal(new[] { HttpStatusCode.Created, HttpStatusCode.Conflict }, responses.Select(x => x.StatusCode).Order());
    var me = await Object(harness.GetAsync("/api/rights/me?user_id=" + user)); var choice = me["requestable_skills"]!.AsArray().Single(x => x!["name"]!.GetValue<string>() == skill.Name)!;
    Assert.Equal("pending", choice["requested"]!.GetValue<string>()); Assert.True(choice.AsObject().ContainsKey("description"));
    var row = await db.SkillRequests.SingleAsync(x => x.UserId == user);
    await Object(admin.GetAsync("/api/admin/skill-requests/count?status=pending"));
    var list = await admin.GetFromJsonAsync<JsonArray>("/api/admin/skill-requests?status=pending&limit=200"); Assert.Contains(row.Id.ToString(), list!.ToJsonString());
    Assert.Equal(HttpStatusCode.BadRequest, (await admin.GetAsync("/api/admin/skill-requests?after=bad")).StatusCode);
    await Object(admin.PostAsJsonAsync($"/api/admin/skill-requests/{row.Id}/approve", new { }));
    var key = JsonNode.Parse(skill.Manifest)!["right"]!.GetValue<string>(); Assert.True(await db.Grants.AnyAsync(x => x.SubjectId == user && x.RightKey == key && x.DeletedAt == null));
    await Code(Request(), HttpStatusCode.BadRequest, "skill_not_requestable");
    foreach (var audit in await db.Audit.Where(x => x.Target == user && x.Action.StartsWith("skill.")).ToListAsync()) Assert.DoesNotContain(reason, audit.Detail);
    Assert.DoesNotContain(host.Logs.Entries, x => x.Contains(reason, StringComparison.Ordinal));
    skill.DeletedAt = DateTimeOffset.UtcNow; await db.SaveChangesAsync();
  }
  [DatabaseFact]
  public async Task SkillRejectionCooldownCapAndNoAccessDecision()
  {
    await Migrate(); var clock = new TestClock(); using var host = new Host(true) { Clock = clock }; using var admin = host.Client(); using var harness = host.Client("harness");
    await using var db = Database(); var skill = await Skill(db); var user = "synthetic-" + Guid.NewGuid();
    var access = new AccessRequest { UserId = user, Status = "approved" }; db.AccessRequests.Add(access); await db.SaveChangesAsync();
    Task<HttpResponseMessage> Request() => harness.PostAsJsonAsync("/api/skill-requests", new { user_id = user, skill = skill.Name });
    var first = await Object(Request(), HttpStatusCode.Created); var id = first["id"]!.GetValue<string>();
    await Object(admin.PostAsJsonAsync($"/api/admin/skill-requests/{id}/reject", new { }));
    await Code(Request(), HttpStatusCode.Conflict, "too_soon"); clock.Now = clock.Now.AddDays(7);
    var second = await Object(Request(), HttpStatusCode.Created); var secondId = second["id"]!.GetValue<string>();
    access.Status = "rejected"; await db.SaveChangesAsync();
    await Code(admin.PostAsJsonAsync($"/api/admin/skill-requests/{secondId}/approve", new { }), HttpStatusCode.Conflict, "not_approved");
    access.Status = "approved"; await db.SaveChangesAsync();
    await Object(admin.PostAsJsonAsync($"/api/admin/skill-requests/{secondId}/reject", new { })); clock.Now = clock.Now.AddDays(7);
    for (var n = 0; n < 20; n++) db.SkillRequests.Add(new SkillRequest { UserId = user, Skill = "synthetic-cap-" + n }); await db.SaveChangesAsync();
    await Code(Request(), HttpStatusCode.TooManyRequests, "too_many_requests");
    foreach (var row in await db.SkillRequests.Where(x => x.UserId == user && x.Status == "pending").ToListAsync()) await Object(admin.PostAsJsonAsync($"/api/admin/skill-requests/{row.Id}/reject", new { }));
    skill.DeletedAt = DateTimeOffset.UtcNow; await db.SaveChangesAsync();
  }
  [DatabaseFact]
  public async Task ModelHealthOnlyGatewayInternalPortAndValidStatusAndReason()
  {
    await Migrate(); using var host = new Host(true); using var gateway = host.Client("gateway", port: 8081); using var admin = host.Client();
    await using var db = Database(); var row = new ModelEntry { Purpose = "classification", Role = "main", Location = "cloud", ApiType = "synthetic", RateLimitPerMinute = 1 }; db.Models.Add(row); await db.SaveChangesAsync();
    var path = $"/api/models/{row.Id}/health";
    Assert.Equal(HttpStatusCode.NotFound, (await admin.PostAsJsonAsync(path, new { status = "ok" })).StatusCode);
    foreach (var role in new[] { "admin", "harness", "other" }) { using var client = host.Client(role, port: 8081); await Code(client.PostAsJsonAsync(path, new { status = "ok" }), HttpStatusCode.Forbidden, "forbidden"); }
    foreach (var body in new[] { new { status = "bad", reason = "timeout" }, new { status = "down", reason = "private provider text" } }) await Code(gateway.PostAsJsonAsync(path, body), HttpStatusCode.BadRequest, "invalid_input");
    await Object(gateway.PostAsJsonAsync(path, new { status = "down", reason = "http_503" }));
    var view = await Object(admin.GetAsync($"/api/admin/models/{row.Id}")); Assert.Equal("down", view["health"]!.GetValue<string>()); Assert.Equal("http_503", view["health_reason"]!.GetValue<string>()); Assert.NotNull(view["health_changed_at"]);
    await Object(gateway.PostAsJsonAsync(path, new { status = "ok" })); row.DeletedAt = DateTimeOffset.UtcNow; await db.SaveChangesAsync();
  }
  [DatabaseFact]
  public async Task DeadLettersDeduplicateByBrokerPositionIncludingMalformedMessagesAndAreImmutable()
  {
    await Migrate(); await using var db = Database(); var handler = new DeadLetterConsumer(db); var offset = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
    var position = new ConsumeResult<string, string> { Topic = "dlq.chat.messages", Partition = 1, Offset = offset };
    var node = RoutesWithoutDatabaseTests.Envelope(); node["type"] = "dlq.entry"; node["payload"] = new JsonObject { ["original_message"] = "Synthetic original", ["error"] = new JsonObject { ["code"] = "synthetic", ["message"] = "Synthetic failure" } };
    var record = new KafkaRecord(position.Topic, node.ToJsonString(), position);
    await handler.Handle(record, TestContext.Current.CancellationToken); await handler.Handle(record, TestContext.Current.CancellationToken);
    Assert.Equal(1, await db.DeadLetters.CountAsync(x => x.Topic == position.Topic && x.Offset == offset));
    position = new ConsumeResult<string, string> { Topic = position.Topic, Partition = 1, Offset = offset + 1 };
    await handler.Handle(new(position.Topic, "not json", position), TestContext.Current.CancellationToken);
    using var host = new Host(true); using var admin = host.Client();
    var list = await admin.GetFromJsonAsync<JsonArray>("/api/admin/dead-letters?topic=dlq.chat.messages&limit=1"); Assert.Single(list!);
    var cursor = list![0]!["received_at"] + "," + list[0]!["id"];
    Assert.Equal(HttpStatusCode.OK, (await admin.GetAsync("/api/admin/dead-letters?before=" + Uri.EscapeDataString(cursor))).StatusCode);
    await Object(admin.GetAsync("/api/admin/dead-letters/count"));
    foreach (var owner in new[] { false, true }) foreach (var operation in new[] { "UPDATE dead_letters SET error_code='changed'", "DELETE FROM dead_letters", "TRUNCATE dead_letters", "DELETE FROM skill_requests", "TRUNCATE skill_requests" })
    {
      await using var role = Database(owner); await using var tx = await role.Database.BeginTransactionAsync();
      await Assert.ThrowsAsync<Npgsql.PostgresException>(() => role.Database.ExecuteSqlRawAsync(operation)); await tx.RollbackAsync();
    }
  }
  [DatabaseFact]
  public async Task ApprovalDetailsStayInApprovalsAndNeverInAudit()
  {
    await Migrate(); using var host = new Host(true); using var admin = host.Client(); using var scope = host.Services.CreateScope();
    var db = scope.ServiceProvider.GetRequiredService<CentreDb>(); var node = RoutesWithoutDatabaseTests.Envelope();
    var text = "Synthetic flagged excerpt"; node["payload"]!["action"] = "safety.flag"; node["payload"]!["details"] = new JsonObject { ["excerpt"] = text }; node["payload"]!["risk"] = "safety";
    await scope.ServiceProvider.GetRequiredService<ApprovalConsumer>().Handle(new("approvals.requested", node.ToJsonString(), new object()), TestContext.Current.CancellationToken);
    var id = Guid.Parse(node["event_id"]!.GetValue<string>()); var row = await db.Approvals.SingleAsync(x => x.RequestEventId == id); Assert.Contains(text, row.Details);
    await Object(admin.PostAsJsonAsync($"/api/admin/approvals/{row.Id}/decision", new { approved = false, note = "Synthetic clear" }));
    foreach (var audit in await db.Audit.Where(x => x.Target == row.Id.ToString()).ToListAsync()) { Assert.DoesNotContain(text, audit.Detail); Assert.DoesNotContain("details", audit.Detail); }
  }
  [DatabaseFact]
  public async Task ObservePersistsServiceMarkerAndHidesPeopleAndRequests()
  {
    await Migrate(); using var host = new Host(true); using var admin = host.Client(); using var harness = host.Client("harness"); var user = "synthetic-" + Guid.NewGuid();
    await Object(harness.PostAsJsonAsync("/api/access/observe", new { user_id = user, is_admin = false, is_service_account = true }));
    await using var db = Database(); Assert.True((await db.AccessRequests.SingleAsync(x => x.UserId == user)).IsServiceAccount); Assert.True((await db.People.SingleAsync(x => x.UserId == user)).IsServiceAccount);
    Assert.DoesNotContain(user, await admin.GetStringAsync("/api/admin/people?limit=200")); Assert.DoesNotContain(user, await admin.GetStringAsync("/api/admin/access-requests?status=pending&limit=200"));
    // Exercise the Control Centre's own verified-token observation for both marker rules.
    foreach (var claim in new[] { new Claim("client_id", "synthetic-client"), new Claim("preferred_username", "service-account-synthetic") })
    {
      var context = new Microsoft.AspNetCore.Http.DefaultHttpContext(); var actor = "synthetic-" + Guid.NewGuid();
      context.User = new ClaimsPrincipal(new ClaimsIdentity(new[] { new Claim("sub", actor), new Claim("realm_access", "{\"roles\":[\"ooh-admin\"]}"), claim }, "test"));
      await People.Observe(context, db); Assert.True((await db.People.SingleAsync(x => x.UserId == actor)).IsServiceAccount); Assert.True((await db.AccessRequests.SingleAsync(x => x.UserId == actor)).IsServiceAccount);
    }
  }
  [DatabaseFact]
  public async Task OverviewMissingHelpersReturnsNullAndNeedsAttentionUsesLastDay()
  {
    await Migrate(); using var host = new Host(true); using var admin = host.Client();
    var result = await Object(admin.GetAsync("/api/admin/overview"));
    foreach (var key in new[] { "skill_jobs_today", "model_calls_today", "cost_today_usd" }) { Assert.True(result.ContainsKey(key)); Assert.Null(result[key]); }
    Assert.NotNull(result["people_active_today"]); Assert.NotNull(result["people_approved"]); Assert.Equal(8, result["health"]!.AsArray().Count);
    var health = await admin.GetFromJsonAsync<JsonArray>("/api/admin/health"); Assert.Equal(8, health!.Count);
    foreach (var row in health) Assert.Equal("unknown", row!["status"]!.GetValue<string>());
    await Code(admin.GetAsync("/api/admin/trail?correlation_id=bad"), HttpStatusCode.BadRequest, "invalid_input");
    await Code(admin.GetAsync("/api/admin/trail?before_id=0"), HttpStatusCode.BadRequest, "invalid_input");
    await Code(admin.GetAsync("/api/admin/trail"), HttpStatusCode.ServiceUnavailable, "unavailable");
  }
  [DatabaseFact]
  public async Task OverviewKeepsEachHelpersFiguresIndependentAndTrailForwardsFiltersWithServiceToken()
  {
    await Migrate();
    Environment.SetEnvironmentVariable("CC_AUDIT_WRITER_URL", "http://audit.invalid:8080"); Environment.SetEnvironmentVariable("CC_COST_METER_URL", "http://cost.invalid:8080");
    try
    {
      using var host = new Host(true, "synthetic-service-secret"); using var admin = host.Client(); var countsDown = false; var costDown = false;
      host.Gateway.Answer = _ => Task.FromResult(host.Gateway.GatewayUrl switch
      {
        "/v1/counts" => countsDown ? new HttpResponseMessage(HttpStatusCode.ServiceUnavailable) : new HttpResponseMessage(HttpStatusCode.OK) { Content = JsonContent.Create(new { distinct_users = 3, by_action = new Dictionary<string, int> { ["skill.requested"] = 2, ["model.call"] = 4, ["model.classify"] = 5 } }) },
        "/v1/costs" => costDown ? new HttpResponseMessage(HttpStatusCode.ServiceUnavailable) : new HttpResponseMessage(HttpStatusCode.OK) { Content = JsonContent.Create(new { total_usd = 0.25m }) },
        _ => new HttpResponseMessage(HttpStatusCode.OK) { Content = JsonContent.Create(new[] { new { id = 1, action = "synthetic" } }) }
      });
      var view = await Object(admin.GetAsync("/api/admin/overview")); var activePeople = view["people_active_today"]!.GetValue<int>(); Assert.True(activePeople >= 0); Assert.Equal(2, view["skill_jobs_today"]!.GetValue<int>()); Assert.Equal(9, view["model_calls_today"]!.GetValue<int>()); Assert.Equal(0.25m, view["cost_today_usd"]!.GetValue<decimal>());
      countsDown = true; view = await Object(admin.GetAsync("/api/admin/overview")); Assert.Null(view["model_calls_today"]); Assert.Equal(activePeople, view["people_active_today"]!.GetValue<int>()); Assert.Equal(0.25m, view["cost_today_usd"]!.GetValue<decimal>());
      countsDown = false; costDown = true; view = await Object(admin.GetAsync("/api/admin/overview")); Assert.Equal(9, view["model_calls_today"]!.GetValue<int>()); Assert.Null(view["cost_today_usd"]);
      var correlation = Guid.NewGuid(); var trail = await admin.GetFromJsonAsync<JsonArray>($"/api/admin/trail?correlation_id={correlation}&user_id=synthetic-user&actor=synthetic&action=model.call&before_id=2&limit=10"); Assert.Single(trail!); Assert.Equal("Bearer synthetic-service-token", host.Gateway.Authorization);
    }
    finally { Environment.SetEnvironmentVariable("CC_AUDIT_WRITER_URL", null); Environment.SetEnvironmentVariable("CC_COST_METER_URL", null); }
  }
  [Fact]
  public async Task PollerChecksAllServicesMetadataAndDiscoveryAndTracksFailures()
  {
    var transport = new TestGatewayHttp(); var down = false;
    transport.Answer = _ => Task.FromResult(down ? new HttpResponseMessage(HttpStatusCode.ServiceUnavailable) : new HttpResponseMessage(HttpStatusCode.OK) { Content = JsonContent.Create(new { status = "ok", issuer = "https://issuer.invalid" }) });
    using var http = new HttpClient(transport); var settings = ServiceHealth.Services.ToDictionary(x => "CC_" + x.Replace('-', '_').ToUpperInvariant() + "_URL", x => (string?)"http://synthetic.invalid"); settings["CC_OIDC_ISSUER"] = "https://issuer.invalid";
    settings["CC_GATEWAY_URL"] = settings["CC_MODEL_GATEWAY_URL"]; settings.Remove("CC_MODEL_GATEWAY_URL");
    var config = new ConfigurationBuilder().AddInMemoryCollection(settings).Build(); var state = new ServiceHealth(); Assert.All(state.Rows, x => Assert.Equal("unknown", x.Status));
    var poller = new HealthPoller(state, http, config, new FakeKafka(), TimeProvider.System); await poller.Refresh(TestContext.Current.CancellationToken); Assert.Equal(8, state.Rows.Length); Assert.All(state.Rows, x => Assert.Equal("ok", x.Status));
    down = true; await poller.Refresh(TestContext.Current.CancellationToken); Assert.All(state.Rows.Where(x => x.Name != "kafka"), x => Assert.Equal("down", x.Status));
  }

  [DatabaseFact]
  public async Task AdminModelListReturnsUpdatedClassificationHealthWithoutTier()
  {
    await Migrate(); using var host = new Host(true); using var admin = host.Client(); using var gateway = host.Client("gateway", port: 8081);
    await using var db = Database();
    var entry = new ModelEntry { Purpose = "classification", Tier = null, Title = "Synthetic classifier", Role = "main", Location = "cloud", ApiType = "synthetic", ModelId = "synthetic-" + Guid.NewGuid(), EndpointUrl = "https://synthetic.invalid", RateLimitPerMinute = 1 };
    db.Models.Add(entry); await db.SaveChangesAsync();
    async Task<JsonNode> Listed()
    {
      var after = "";
      while (true)
      {
        var page = (await admin.GetFromJsonAsync<JsonArray>("/api/admin/models?limit=200" + after))!;
        var row = page.SingleOrDefault(x => x!["model_entry_id"]!.GetValue<Guid>() == entry.Id);
        if (row is not null) return row;
        Assert.Equal(200, page.Count);
        after = "&after=" + page[^1]!["model_entry_id"]!.GetValue<string>();
      }
    }
    try
    {
      Assert.Equal("unknown", (await Listed())["health"]!.GetValue<string>());
      await Object(gateway.PostAsJsonAsync($"/api/models/{entry.Id}/health", new { status = "ok" }));
      var view = await Listed(); Assert.Equal("ok", view["health"]!.GetValue<string>()); Assert.NotNull(view["health_changed_at"]);
      Assert.False(view.AsObject().ContainsKey("tier"));
      Assert.Equal("classification", view["purpose"]!.GetValue<string>());
      Assert.Equal("ok", (await Object(admin.GetAsync($"/api/admin/models/{entry.Id}")))["health"]!.GetValue<string>());
    }
    finally { entry.DeletedAt = DateTimeOffset.UtcNow; await db.SaveChangesAsync(); }
  }

}
