// SPDX-License-Identifier: AGPL-3.0-only
using System.Net;
using System.Net.Http.Json;
using System.Text.Json.Nodes;
using ControlCentre.Platform;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Npgsql;
using Xunit;
using static ControlCentre.Tests.RoutesWithoutDatabaseTests;

namespace ControlCentre.Tests;

public sealed class DatabaseTests
{
  private static CentreDb Database(bool owner = false)
  {
    var settings = TestSettings.Load();
    return new CentreDb(new DbContextOptionsBuilder<CentreDb>().UseNpgsql(DatabaseConnections.Configure(settings[owner ? "CC_TEST_DB_MIGRATE_CONNECTION" : "CC_TEST_DB_CONNECTION"])).Options);
  }
  private static async Task Migrate()
  {
    await using var owner = Database(true);
    await owner.Database.MigrateAsync();
  }
  private static async Task<JsonObject> Object(HttpResponseMessage response, HttpStatusCode expected = HttpStatusCode.OK)
  {
    Assert.Equal(expected, response.StatusCode);
    return (await response.Content.ReadFromJsonAsync<JsonObject>())!;
  }
  private static JsonObject Model(int tier) => new()
  {
    ["purpose"] = "chat",
    ["tier"] = tier,
    ["role"] = "backup",
    ["location"] = "cloud",
    ["api_type"] = "test",
    ["endpoint_url"] = "https://test.invalid",
    ["model_id"] = "test",
    ["secret_ref"] = "test-none",
    ["rate_limit_per_minute"] = 1,
    ["daily_budget"] = 0
  };
  [DatabaseFact]
  public async Task RegistryGrantsRightsPeopleAndAuditRoutes()
  {
    await Migrate();
    using var host = new Host(true);
    using var admin = host.Client(); using var harness = host.Client("harness"); using var gateway = host.Client("gateway", port: 8081);
    var user = "test-" + Guid.NewGuid();
    var tier = Random.Shared.Next(100000, int.MaxValue);
    Assert.Equal(HttpStatusCode.OK, (await host.CreateClient().GetAsync("/health")).StatusCode);
    var created = await Object(await admin.PostAsJsonAsync("/api/admin/models", Model(tier)), HttpStatusCode.Created);
    var modelId = created["model_entry_id"]!.GetValue<string>();
    await Object(await admin.GetAsync("/api/admin/models/" + modelId));
    Assert.Equal(HttpStatusCode.Created, (await admin.PostAsJsonAsync("/api/admin/models", Model(tier))).StatusCode);
    Assert.NotEmpty((await gateway.GetFromJsonAsync<JsonArray>($"/api/models?purpose=chat&tier={tier}"))!);
    Assert.Equal(HttpStatusCode.Forbidden, (await harness.GetAsync("http://localhost:8081/api/models?purpose=classification")).StatusCode);
    var changed = Model(tier); changed["daily_budget"] = 1;
    await Object(await admin.PutAsJsonAsync("/api/admin/models/" + modelId, changed));
    var right = "chat.tier." + tier;
    var rights = await admin.GetFromJsonAsync<JsonArray>("/api/admin/rights?limit=200");
    await using (var db = Database()) Assert.True(await db.Rights.AnyAsync(x => x.Key == right));
    var check = new { user_id = user, action = "chat.tier", target = tier.ToString() };
    var denied = await Object(await harness.PostAsJsonAsync("/api/rights/check", check));
    Assert.False(denied["allowed"]!.GetValue<bool>()); Assert.Equal("no-grant", denied["decided_by"]!.GetValue<string>());
    var grant = await Object(await admin.PostAsJsonAsync("/api/admin/grants", new { right_key = right, subject_type = "user", subject_id = user }), HttpStatusCode.Created);
    var allowed = await Object(await harness.PostAsJsonAsync("/api/rights/check", check));
    Assert.Equal("grant:user", allowed["decided_by"]!.GetValue<string>());
    var me = await Object(await harness.GetAsync("/api/rights/me?user_id=" + user));
    Assert.Contains(me["chat_tiers"]!.AsArray(), x => x!.GetValue<int>() == tier);
    var person = await Object(await admin.GetAsync("/api/admin/people/" + user));
    Assert.NotEmpty(person["grants"]!.AsArray());
    Assert.Equal(HttpStatusCode.OK, (await admin.GetAsync("/api/admin/people?limit=1")).StatusCode);
    var everyone = await Object(await admin.PostAsJsonAsync("/api/admin/grants", new { right_key = right, subject_type = "everyone" }), HttpStatusCode.Created);
    allowed = await Object(await harness.PostAsJsonAsync("/api/rights/check", check));
    Assert.Equal("grant:user", allowed["decided_by"]!.GetValue<string>());
    await Object(await admin.DeleteAsync("/api/admin/grants/" + grant["id"]!.GetValue<string>()));
    allowed = await Object(await harness.PostAsJsonAsync("/api/rights/check", check));
    Assert.Equal("grant:everyone", allowed["decided_by"]!.GetValue<string>());
    await Object(await admin.DeleteAsync("/api/admin/grants/" + everyone["id"]!.GetValue<string>()));
    denied = await Object(await harness.PostAsJsonAsync("/api/rights/check", check));
    Assert.False(denied["allowed"]!.GetValue<bool>());
    var image = new { user_id = user, action = "image.generate", target = "ignored" };
    var imageGrant = await Object(await admin.PostAsJsonAsync("/api/admin/grants", new { right_key = "image.generate", subject_type = "user", subject_id = user }), HttpStatusCode.Created);
    allowed = await Object(await harness.PostAsJsonAsync("/api/rights/check", image));
    Assert.True(allowed["allowed"]!.GetValue<bool>());
    me = await Object(await harness.GetAsync("/api/rights/me?user_id=" + user));
    Assert.True(me["image"]!.GetValue<bool>());
    await Object(await admin.DeleteAsync("/api/admin/grants/" + imageGrant["id"]!.GetValue<string>()));
    denied = await Object(await harness.PostAsJsonAsync("/api/rights/check", image));
    Assert.False(denied["allowed"]!.GetValue<bool>());
    var skillName = "test-" + Guid.NewGuid().ToString("N");
    var manifest = ValidManifest(skillName);
    await Object(await admin.PostAsJsonAsync("/api/admin/skills", manifest), HttpStatusCode.Created);
    await Object(await admin.PostAsJsonAsync("/api/admin/skills", manifest));
    await Object(await admin.GetAsync("/api/admin/skills/" + skillName));
    Assert.Equal(HttpStatusCode.OK, (await admin.GetAsync("/api/admin/skills")).StatusCode);
    var skills = (await harness.GetFromJsonAsync<JsonArray>("/api/skills?user_id=" + user))!;
    Assert.DoesNotContain(skills, x => x!["name"]!.GetValue<string>() == skillName);
    await Object(await admin.PostAsJsonAsync("/api/admin/grants", new { right_key = "skill." + skillName, subject_type = "user", subject_id = user }), HttpStatusCode.Created);
    skills = (await harness.GetFromJsonAsync<JsonArray>("/api/skills?user_id=" + user))!;
    Assert.Contains(skills, x => x!["name"]!.GetValue<string>() == skillName);
    var skillDecision = await Object(await harness.PostAsJsonAsync("/api/rights/check", new { user_id = user, action = "skill.use", target = skillName }));
    Assert.True(skillDecision["allowed"]!.GetValue<bool>());
    var invalidManifest = manifest.DeepClone().AsObject(); invalidManifest["extra"] = true;
    Assert.Equal(HttpStatusCode.BadRequest, (await admin.PostAsJsonAsync("/api/admin/skills", invalidManifest)).StatusCode);
    var invalidModel = Model(tier); invalidModel["secret_ref"] = "not a secret name";
    Assert.Equal(HttpStatusCode.BadRequest, (await admin.PostAsJsonAsync("/api/admin/models", invalidModel)).StatusCode);
    manifest["version"] = "1.0.1";
    await Object(await admin.PutAsJsonAsync("/api/admin/skills/" + skillName, manifest));
    await Object(await admin.DeleteAsync("/api/admin/skills/" + skillName));
    skillDecision = await Object(await harness.PostAsJsonAsync("/api/rights/check", new { user_id = user, action = "skill.use", target = skillName }));
    Assert.False(skillDecision["allowed"]!.GetValue<bool>());
    await Object(await admin.DeleteAsync("/api/admin/models/" + modelId));
    Assert.Equal(HttpStatusCode.NotFound, (await admin.GetAsync("/api/admin/models/" + modelId)).StatusCode);
    var audit = (await admin.GetFromJsonAsync<JsonArray>("/api/admin/audit?target=" + right))!;
    Assert.NotEmpty(audit);
    await using (var db = Database())
    {
      Assert.True(await db.Rights.AnyAsync(x => x.Key == right));
      var correlation = Guid.Parse(audit[0]!["correlation_id"]!.GetValue<string>());
      Assert.True(await db.Outbox.AnyAsync(x => x.Key == correlation.ToString() && x.Topic == "audit.events"));
    }
    using var self = host.Client("self", user);
    await Object(await self.GetAsync("/api/rights/me?user_id=" + user));
    await using (var db = Database())
    {
      var seen = await db.People.SingleAsync(x => x.UserId == user);
      Assert.Equal("synthetic-user@test.invalid", seen.Email);
      Assert.Equal("Synthetic User", seen.Name);
    }
    Assert.Equal(HttpStatusCode.Forbidden, (await self.GetAsync("/api/rights/me?user_id=someone-else")).StatusCode);
    Assert.Equal(HttpStatusCode.BadRequest, (await admin.PostAsJsonAsync("/api/admin/grants", new { right_key = right, subject_type = "everyone", subject_id = "bad" })).StatusCode);
  }
  [DatabaseFact]
  public async Task ApprovalConsumerIsIdempotentDecisionIsAtomicAndPagingIsStable()
  {
    await Migrate();
    await using var db = Database();
    var delay = new FakeDelay();
    var consumer = new ApprovalConsumer(db, new SchemaChecks(), delay);
    var envelope = Envelope();
    var record = new KafkaRecord("approvals.requested", envelope.ToJsonString(), new object());
    await consumer.Handle(record, default); await consumer.Handle(record, default);
    var correlation = Guid.Parse(envelope["correlation_id"]!.GetValue<string>());
    Assert.Single(await db.Approvals.Where(x => x.CorrelationId == correlation).ToListAsync());
    Assert.Empty(delay.Waits);
    using var host = new Host(true); using var client = host.Client();
    var list = (await client.GetFromJsonAsync<JsonArray>("/api/admin/approvals?correlation_id=" + correlation))!;
    Assert.Single(list);
    var id = list[0]!["id"]!.GetValue<string>();
    await Object(await client.GetAsync("/api/admin/approvals/" + id));
    await Object(await client.PostAsJsonAsync($"/api/admin/approvals/{id}/decision", new { approved = true, note = "Synthetic decision" }));
    Assert.Equal(HttpStatusCode.Conflict, (await client.PostAsJsonAsync($"/api/admin/approvals/{id}/decision", new { approved = false, note = "" })).StatusCode);
    Assert.Single(await db.Outbox.Where(x => x.Key == correlation.ToString() && x.Topic == "approvals.decided").ToListAsync());
    var sent = await db.Outbox.SingleAsync(x => x.Key == correlation.ToString() && x.Topic == "approvals.decided");
    var decisionEnvelope = JsonNode.Parse(sent.Envelope)!;
    Assert.Equal(envelope["user_id"]!.ToString(), decisionEnvelope["user_id"]!.ToString());
    Assert.Equal(correlation.ToString(), decisionEnvelope["correlation_id"]!.ToString());
    Assert.True(await db.Audit.AnyAsync(x => x.Target == id && x.Action == "approval.decided"));
    var sameTime = DateTimeOffset.UtcNow;
    var others = new[] { new Approval { CorrelationId = correlation, RequestEventId = Guid.NewGuid(), CreatedAt = sameTime }, new Approval { CorrelationId = correlation, RequestEventId = Guid.NewGuid(), CreatedAt = sameTime } };
    db.Approvals.AddRange(others); await db.SaveChangesAsync();
    var first = (await client.GetFromJsonAsync<JsonArray>($"/api/admin/approvals?correlation_id={correlation}&limit=1"))!;
    var timestamp = first[0]!["created_at"]!.GetValue<DateTimeOffset>().UtcDateTime.ToString("O");
    var before = Uri.EscapeDataString(timestamp + "," + first[0]!["id"]!.GetValue<string>());
    var second = (await client.GetFromJsonAsync<JsonArray>($"/api/admin/approvals?correlation_id={correlation}&limit=1&before={before}"))!;
    Assert.Single(second); Assert.NotEqual(first[0]!["id"]!.ToString(), second[0]!["id"]!.ToString());
    Assert.Equal(first[0]!["created_at"]!.ToString(), second[0]!["created_at"]!.ToString());
  }
  [DatabaseFact]
  public async Task InvalidKafkaMessageSavesDlqAndAuditWithoutRetries()
  {
    await Migrate(); await using var db = Database();
    var delay = new FakeDelay(); var consumer = new ApprovalConsumer(db, new SchemaChecks(), delay);
    var node = Envelope(); node["payload"]!.AsObject().Remove("risk");
    var record = new KafkaRecord("approvals.requested", node.ToJsonString(), new object());
    await consumer.Handle(record, default); await consumer.Handle(record, default);
    Assert.Empty(delay.Waits);
    var correlation = node["correlation_id"]!.GetValue<string>();
    var dlq = Assert.Single(await db.Outbox.Where(x => x.Key == correlation && x.Topic == "dlq.approvals.requested").ToListAsync());
    Assert.Equal(node["user_id"]!.ToString(), JsonNode.Parse(dlq.Envelope)!["user_id"]!.ToString());
    Assert.True(await db.Audit.AnyAsync(x => x.CorrelationId.ToString() == correlation && x.Actor == "system"));
    var priorIds = await db.Outbox.Select(x => x.Id).ToListAsync();
    await consumer.Handle(new KafkaRecord("approvals.requested", "{unreadable", new object()), default);
    var unreadable = Assert.Single(await db.Outbox.Where(x => !priorIds.Contains(x.Id) && x.Topic == "dlq.approvals.requested").ToListAsync());
    var parsed = JsonNode.Parse(unreadable.Envelope)!;
    Assert.Equal("system", parsed["user_id"]!.GetValue<string>());
    Assert.Equal(parsed["correlation_id"]!.ToString(), unreadable.Key);
    Assert.Empty(delay.Waits);
  }
  [DatabaseFact]
  public async Task OutboxSavedAtomicallyAndPublishedOnceWithFakeKafka()
  {
    await Migrate(); await using var db = Database();
    var correlation = Guid.NewGuid();
    await using (var tx = await db.Database.BeginTransactionAsync())
    {
      Api.Change(db, "system", "test.rollback", "test", correlation, new { });
      await db.SaveChangesAsync();
      await tx.RollbackAsync();
    }
    db.ChangeTracker.Clear();
    Assert.False(await db.Audit.AnyAsync(x => x.CorrelationId == correlation));
    Assert.False(await db.Outbox.AnyAsync(x => x.Key == correlation.ToString()));
    var fake = new FakeKafka();
    Api.Change(db, "system", "test.publish", "test", correlation, new { });
    await db.SaveChangesAsync();
    var publisher = new OutboxPublisher(db, fake);
    for (var i = 0; i < 100 && !fake.Published.Any(x => x.Key == correlation.ToString()); i++) await publisher.Publish(default);
    Assert.Single(fake.Published, x => x.Key == correlation.ToString());
    await publisher.Publish(default);
    Assert.Single(fake.Published, x => x.Key == correlation.ToString());
    fake.Fail = true;
    Api.Event(db, "audit.events", "audit.event", Guid.NewGuid(), "system", new { actor = "system", action = "test", target = "test", outcome = "success" });
    await db.SaveChangesAsync();
    var unsent = db.ChangeTracker.Entries<Outbox>().Last().Entity.Id;
    await Assert.ThrowsAsync<IOException>(() => publisher.Publish(default)); db.ChangeTracker.Clear();
    Assert.Null((await db.Outbox.FindAsync(unsent))!.SentAt);
  }
  [DatabaseFact]
  public async Task DatabaseOwnerTriggersAndApplicationPermissionsProtectAllTables()
  {
    await Migrate();
    foreach (var owner in new[] { false, true })
    {
      await using var db = Database(owner);
      foreach (var sql in new[] { "UPDATE audit_log SET outcome = outcome WHERE id = (SELECT min(id) FROM audit_log)", "DELETE FROM audit_log WHERE id = (SELECT min(id) FROM audit_log)", "TRUNCATE audit_log" })
      {
        await using var transaction = await db.Database.BeginTransactionAsync();
        var error = await Assert.ThrowsAsync<PostgresException>(() => db.Database.ExecuteSqlRawAsync(sql));
        if (owner) Assert.Contains("append-only", error.MessageText);
        else Assert.Equal("42501", error.SqlState);
        await transaction.RollbackAsync();
      }
      foreach (var table in new[] { "people", "rights", "grants", "model_entries", "skills", "approvals", "processed_events", "outbox" })
        foreach (var verb in new[] { "DELETE FROM", "TRUNCATE" })
        {
          await using var transaction = await db.Database.BeginTransactionAsync();
          // Both SQL identifiers come only from the fixed table and verb lists above.
#pragma warning disable EF1003
          var error = await Assert.ThrowsAsync<PostgresException>(() => db.Database.ExecuteSqlRawAsync(verb + " " + table + (verb == "TRUNCATE" ? " CASCADE" : "")));
#pragma warning restore EF1003
          if (owner) Assert.Contains("forbidden", error.MessageText);
          else Assert.Equal("42501", error.SqlState);
          await transaction.RollbackAsync();
        }
    }
  }
}
