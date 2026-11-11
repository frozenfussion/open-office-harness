// SPDX-License-Identifier: AGPL-3.0-only
using System.Net;
using System.Net.Http.Json;
using System.Text.Json.Nodes;
using ControlCentre.Access;
using ControlCentre.Platform;
using Microsoft.EntityFrameworkCore;
using Xunit;

namespace ControlCentre.Tests;

public sealed class AccessTests
{
  private static CentreDb Database(bool owner = false) => new(new DbContextOptionsBuilder<CentreDb>().UseNpgsql(DatabaseConnections.Configure(TestSettings.Load()[owner ? "CC_TEST_DB_MIGRATE_CONNECTION" : "CC_TEST_DB_CONNECTION"])).Options);
  private sealed class Fixture : IAsyncDisposable
  {
    public Host Host { get; } = new(true);
    public HttpClient Admin { get; }
    public HttpClient Harness { get; }
    public HashSet<string> Users { get; } = [];
    private readonly string prefix = "access-test-" + Guid.NewGuid().ToString("N") + "-";
    private Fixture() { Admin = Host.Client(); Harness = Host.Client("harness"); }
    public static async Task<Fixture> Create()
    { await using var owner = Database(true); await owner.Database.MigrateAsync(); return new Fixture(); }
    public string User(string suffix = "user") { var user = prefix + suffix; Users.Add(user); return user; }
    public async Task<JsonObject> Observe(string user, bool admin = false, string name = "Synthetic Applicant")
    {
      Users.Add(user);
      return await Object(await Harness.PostAsJsonAsync("/api/access/observe", new { user_id = user, is_admin = admin, name, email = "synthetic@access.invalid", organisation = "Synthetic team", access_reason = "Synthetic request reason" }));
    }
    public async Task<int> Tier()
    {
      var tier = System.Security.Cryptography.RandomNumberGenerator.GetInt32(100000, int.MaxValue);
      await using var db = Database(); db.Rights.Add(new Right { Key = "chat.tier." + tier, Source = "tier" }); await db.SaveChangesAsync(); return tier;
    }
    public async Task<AccessRequest> Row(string user)
    { await using var db = Database(); return await db.AccessRequests.SingleAsync(x => x.UserId == user); }
    public async ValueTask DisposeAsync()
    {
      await using var db = Database(); await using var transaction = await db.Database.BeginTransactionAsync(); await AccessPolicy.Lock(db);
      foreach (var row in await db.AccessRequests.Where(x => Users.Contains(x.UserId) && x.Status == "pending").ToListAsync())
      {
        row.Status = "rejected"; row.DecidedBy = "test:cleanup"; row.DecidedAt = DateTimeOffset.UtcNow; Api.Stamp(row, "test:cleanup");
        AccessPolicy.Audit(db, row, "access.rejected", "test:cleanup", Guid.NewGuid());
      }
      await db.SaveChangesAsync(); await transaction.CommitAsync(); Admin.Dispose(); Harness.Dispose(); await Host.DisposeAsync();
    }
  }
  private static async Task<JsonObject> Object(HttpResponseMessage response, HttpStatusCode expected = HttpStatusCode.OK)
  { Assert.Equal(expected, response.StatusCode); return (await response.Content.ReadFromJsonAsync<JsonObject>())!; }
  [DatabaseFact]
  public async Task ObserveIsIdempotentUpdatesOnlyPendingAndAuditsNoProfileData()
  {
    await using var f = await Fixture.Create(); var user = f.User();
    Assert.Equal("pending", (await f.Observe(user))["status"]!.GetValue<string>());
    var first = await f.Row(user); await f.Observe(user); await f.Observe(user, name: "Changed Synthetic Applicant");
    Assert.Equal(first.RequestedAt, (await f.Row(user)).RequestedAt);
    await using var db = Database();
    var audits = await db.Audit.Where(x => x.Target == user && x.Action.StartsWith("access.")).ToListAsync(); Assert.Equal(2, audits.Count);
    foreach (var row in audits)
    {
      var detail = JsonNode.Parse(row.Detail)!.AsObject();
      Assert.Equal(new[] { "approved_tier", "decided_by", "status", "user_id" }, detail.Select(x => x.Key).Order());
      var envelope = (await db.Outbox.Where(x => x.Key == row.CorrelationId.ToString() && x.Topic == "audit.events").ToListAsync()).Single(x => JsonNode.Parse(x.Envelope)!["payload"]!["action"]!.GetValue<string>() == row.Action);
      foreach (var secret in new[] { "Synthetic Applicant", "synthetic@access.invalid", "Synthetic team", "Synthetic request reason" })
      {
        Assert.DoesNotContain(secret, row.Detail); Assert.DoesNotContain(secret, envelope.Envelope);
        foreach (var log in f.Host.Logs.Entries) Assert.DoesNotContain(secret, log);
      }
    }
    await Object(await f.Admin.PostAsJsonAsync($"/api/admin/access-requests/{first.Id}/reject", new { }));
    Assert.Equal("rejected", (await f.Observe(user, name: "Ignored profile"))["status"]!.GetValue<string>());
    Assert.Equal("Changed Synthetic Applicant", (await f.Row(user)).Name);
    var tier = await f.Tier(); await Object(await f.Admin.PostAsJsonAsync($"/api/admin/access-requests/{first.Id}/approve", new { tier }));
    Assert.Equal("approved", (await f.Observe(user, name: "Ignored approved profile"))["status"]!.GetValue<string>());
    Assert.Equal("Changed Synthetic Applicant", (await f.Row(user)).Name);
  }
  [DatabaseFact]
  public async Task ObserveRejectsOtherCallersValidatesLimitsAndPreservesExactIdentity()
  {
    await using var f = await Fixture.Create(); var user = f.User();
    foreach (var role in new[] { "admin", "self", "gateway", "other" })
    {
      using var client = f.Host.Client(role);
      Assert.Equal(HttpStatusCode.Forbidden, (await client.PostAsJsonAsync("/api/access/observe", new { user_id = user, is_admin = false })).StatusCode);
    }
    foreach (var (field, limit) in new[] { ("name", 200), ("email", 320), ("organisation", 100), ("access_reason", 300) })
    {
      var body = new JsonObject { ["user_id"] = user, ["is_admin"] = false, [field] = new string('x', limit + 1) };
      Assert.Equal(HttpStatusCode.BadRequest, (await f.Harness.PostAsJsonAsync("/api/access/observe", body)).StatusCode);
      body[field] = "  " + new string('x', limit) + "  "; await Object(await f.Harness.PostAsJsonAsync("/api/access/observe", body));
    }
    var other = user.ToUpperInvariant(); f.Users.Add(other); await f.Observe(other);
    Assert.NotEqual((await f.Row(user)).Id, (await f.Row(other)).Id);
    Assert.Equal(other, (await f.Row(other)).UserId);
    Assert.Equal(HttpStatusCode.BadRequest, (await f.Harness.PostAsJsonAsync("/api/access/observe", new { user_id = user, is_admin = "true" })).StatusCode);
  }
  [DatabaseFact]
  public async Task EveryRightsPathGatesEveryoneForPendingRejectedUnknownAndRevokedUsers()
  {
    await using var f = await Fixture.Create(); var tier = await f.Tier(); var skillName = "access-" + Guid.NewGuid().ToString("N");
    await Object(await f.Admin.PostAsJsonAsync("/api/admin/skills", RoutesWithoutDatabaseTests.ValidManifest(skillName)), HttpStatusCode.Created);
    var grants = new List<string>();
    try
    {
      foreach (var key in new[] { "chat.tier." + tier, "skill." + skillName, "image.generate" })
      {
        var grant = await Object(await f.Admin.PostAsJsonAsync("/api/admin/grants", new { right_key = key, subject_type = "everyone" }), HttpStatusCode.Created);
        grants.Add(grant["id"]!.GetValue<string>());
      }
      foreach (var state in new[] { "unknown", "pending", "rejected", "revoked" })
      {
        var user = f.User(state);
        if (state != "unknown") await f.Observe(user, admin: state == "revoked");
        if (state is "rejected" or "revoked")
          await Object(await f.Admin.PostAsJsonAsync($"/api/admin/access-requests/{(await f.Row(user)).Id}/{(state == "revoked" ? "revoke" : "reject")}", new { }));
        var decision = await Object(await f.Harness.PostAsJsonAsync("/api/rights/check", new { user_id = user, action = "chat.tier", target = tier.ToString() }));
        Assert.False(decision["allowed"]!.GetValue<bool>());
        var me = await Object(await f.Harness.GetAsync("/api/rights/me?user_id=" + user));
        Assert.Empty(me["chat_tiers"]!.AsArray()); Assert.Empty(me["chat_tier_titles"]!.AsObject()); Assert.Empty(me["skills"]!.AsArray()); Assert.False(me["image"]!.GetValue<bool>());
        Assert.Empty((await f.Harness.GetFromJsonAsync<JsonArray>("/api/skills?user_id=" + user))!);
      }
      var approved = f.User("approved"); await f.Observe(approved, true);
      var allowed = await Object(await f.Harness.GetAsync("/api/rights/me?user_id=" + approved));
      Assert.Contains(tier, allowed["chat_tiers"]!.AsArray().Select(x => x!.GetValue<int>())); Assert.True(allowed["image"]!.GetValue<bool>());
      Assert.Contains((await f.Harness.GetFromJsonAsync<JsonArray>("/api/skills?user_id=" + approved))!, x => x!["name"]!.GetValue<string>() == skillName);
    }
    finally { foreach (var id in grants) await f.Admin.DeleteAsync("/api/admin/grants/" + id); }
  }
  [DatabaseFact]
  public async Task ApproveRejectRevokeAreTransactionalAndGrantsAreNotDuplicated()
  {
    await using var f = await Fixture.Create(); var user = f.User(); await f.Observe(user); var row = await f.Row(user); var tier = await f.Tier();
    var path = $"/api/admin/access-requests/{row.Id}";
    Assert.Equal(HttpStatusCode.BadRequest, (await f.Admin.PostAsJsonAsync(path + "/approve", new { tier = 0 })).StatusCode);
    Assert.Equal(HttpStatusCode.BadRequest, (await f.Admin.PostAsJsonAsync(path + "/approve", new { tier = 987654321 })).StatusCode);
    await Object(await f.Admin.PostAsJsonAsync(path + "/reject", new { }));
    Assert.Equal(HttpStatusCode.Conflict, (await f.Admin.PostAsJsonAsync(path + "/reject", new { })).StatusCode);
    var approved = await Object(await f.Admin.PostAsJsonAsync(path + "/approve", new { tier }));
    Assert.Equal(tier, approved["approved_tier"]!.GetValue<int>()); Assert.Equal("approved", approved["status"]!.GetValue<string>());
    Assert.Equal(HttpStatusCode.Conflict, (await f.Admin.PostAsJsonAsync(path + "/approve", new { tier })).StatusCode);
    await Object(await f.Admin.PostAsJsonAsync(path + "/revoke", new { }));
    Assert.Equal(HttpStatusCode.Conflict, (await f.Admin.PostAsJsonAsync(path + "/revoke", new { })).StatusCode);
    await Object(await f.Admin.PostAsJsonAsync(path + "/approve", new { tier }));
    await using var db = Database(); Assert.Single(await db.Grants.Where(x => x.SubjectId == user && x.RightKey == "chat.tier." + tier && x.DeletedAt == null).ToListAsync());
    var audits = await db.Audit.Where(x => x.Target == user && x.Action.StartsWith("access.")).Select(x => x.Action).ToListAsync();
    Assert.Equal(2, audits.Count(x => x == "access.approved")); Assert.Contains("access.revoked", audits); Assert.Contains("access.rejected", audits);
    Assert.Equal(HttpStatusCode.NotFound, (await f.Admin.PostAsJsonAsync($"/api/admin/access-requests/{Guid.NewGuid()}/approve", new { tier })).StatusCode);
  }
  [DatabaseFact]
  public async Task AddingUserGrantsApprovesUnknownAndReapprovesRevokedWithoutDuplicates()
  {
    await using var f = await Fixture.Create(); var user = f.User(); var tier = await f.Tier();
    var grant = new { right_key = "chat.tier." + tier, subject_type = "user", subject_id = user };
    await Object(await f.Admin.PostAsJsonAsync("/api/admin/grants", grant), HttpStatusCode.Created);
    Assert.Equal("approved", (await f.Row(user)).Status);
    await Object(await f.Admin.PostAsJsonAsync($"/api/admin/access-requests/{(await f.Row(user)).Id}/revoke", new { }));
    await Object(await f.Admin.PostAsJsonAsync("/api/admin/grants", grant));
    Assert.Equal("approved", (await f.Row(user)).Status);
    await using var db = Database(); Assert.Single(await db.Grants.Where(x => x.SubjectId == user && x.RightKey == grant.right_key && x.DeletedAt == null).ToListAsync());
    Assert.Equal(2, await db.Audit.CountAsync(x => x.Action == "access.approved" && x.Target == user));
  }
  [DatabaseFact]
  public async Task VerifiedAdminFlagsAndHumanAdminObservationApproveAccess()
  {
    await using var f = await Fixture.Create(); var user = f.User(); await f.Observe(user); var row = await f.Row(user);
    await Object(await f.Admin.PostAsJsonAsync($"/api/admin/access-requests/{row.Id}/reject", new { }));
    Assert.Equal("approved", (await f.Observe(user, true))["status"]!.GetValue<string>());
    Assert.Equal("system:admin-role", (await f.Row(user)).DecidedBy);
    var human = f.User("human-admin"); using var admin = f.Host.Client("person-admin", subject: human);
    await Object(await admin.GetAsync("/api/admin/access-requests/count?status=pending"));
    Assert.Equal("approved", (await f.Row(human)).Status); Assert.Equal("system:admin-role", (await f.Row(human)).DecidedBy);
    var humanRow = await f.Row(human); await Object(await f.Admin.PostAsJsonAsync($"/api/admin/access-requests/{humanRow.Id}/revoke", new { }));
    await Object(await admin.GetAsync("/api/admin/access-requests/count?status=pending"));
    Assert.Equal("approved", (await f.Row(human)).Status);
  }
  [DatabaseFact]
  public async Task ListsFilterPageAndHideCheckUsersAndCountsOnlyAllowPending()
  {
    await using var f = await Fixture.Create(); var users = Enumerable.Range(0, 3).Select(n => f.User("page" + n)).ToArray();
    foreach (var user in users) await f.Observe(user);
    var hidden = "stage-check-" + Guid.NewGuid(); f.Users.Add(hidden); await f.Observe(hidden);
    var page = (await f.Admin.GetFromJsonAsync<JsonArray>("/api/admin/access-requests?limit=2"))!;
    Assert.DoesNotContain(page, x => x!["user_id"]!.GetValue<string>().StartsWith("stage-check-", StringComparison.Ordinal));
    Assert.Equal(2, page.Count);
    var after = page.Last()!["id"]!.GetValue<string>();
    var next = (await f.Admin.GetFromJsonAsync<JsonArray>("/api/admin/access-requests?limit=200&after=" + after))!;
    Assert.DoesNotContain(next, x => page.Any(p => p!["id"]!.GetValue<string>() == x!["id"]!.GetValue<string>()));
    await using var db = Database();
    var expected = await db.AccessRequests.CountAsync(x => x.DeletedAt == null && x.Status == "pending" && !x.IsServiceAccount && !x.UserId.StartsWith("stage-check-") && !x.UserId.StartsWith("service-account-") && !db.People.Any(p => p.UserId == x.UserId && p.IsServiceAccount));
    Assert.Equal(expected, (await Object(await f.Admin.GetAsync("/api/admin/access-requests/count?status=pending")))["count"]!.GetValue<int>());
    foreach (var query in new[] { "?status=invalid", "?limit=201", "?after=bad" })
      Assert.Equal(HttpStatusCode.BadRequest, (await f.Admin.GetAsync("/api/admin/access-requests" + query)).StatusCode);
    Assert.Equal(HttpStatusCode.BadRequest, (await f.Admin.GetAsync("/api/admin/access-requests/count?status=approved")).StatusCode);
    Assert.Equal(HttpStatusCode.BadRequest, (await f.Admin.GetAsync("/api/admin/access-requests/count")).StatusCode);
    await Object(await f.Admin.PostAsJsonAsync($"/api/admin/access-requests/{(await f.Row(users[0])).Id}/reject", new { }));
    var rejected = (await f.Admin.GetFromJsonAsync<JsonArray>("/api/admin/access-requests?status=rejected&limit=200"))!;
    Assert.Contains(rejected, x => x!["user_id"]!.GetValue<string>() == users[0]);
    var approved = (await f.Admin.GetFromJsonAsync<JsonArray>("/api/admin/access-requests?status=approved&limit=200"))!;
    Assert.DoesNotContain(approved, x => x!["user_id"]!.GetValue<string>() == users[1]);
  }
  [DatabaseFact]
  public async Task AdmissionCapIsAtomicAtOneHundredAndRepeatsRemainIdempotent()
  {
    await using var f = await Fixture.Create();
    await using (var db = Database())
    {
      await using var transaction = await db.Database.BeginTransactionAsync(); await AccessPolicy.Lock(db);
      var pending = await db.AccessRequests.CountAsync(x => x.Status == "pending" && x.DeletedAt == null); Assert.True(pending <= 99);
      for (var n = pending; n < 99; n++)
      {
        var row = new AccessRequest { UserId = f.User("cap" + n) }; db.AccessRequests.Add(row);
        AccessPolicy.Audit(db, row, "access.requested", "test:seed", Guid.NewGuid());
      }
      await db.SaveChangesAsync(); await transaction.CommitAsync();
    }
    var first = f.User("first"); var second = f.User("second");
    var answers = await Task.WhenAll(f.Observe(first), f.Observe(second));
    Assert.Equal(new[] { "closed", "pending" }, answers.Select(x => x["status"]!.GetValue<string>()).Order());
    var accepted = answers[0]["status"]!.GetValue<string>() == "pending" ? first : second;
    var refused = accepted == first ? second : first;
    Assert.Equal("pending", (await f.Observe(accepted))["status"]!.GetValue<string>());
    Assert.Equal("approved", (await f.Observe(f.User("admin-at-cap"), true))["status"]!.GetValue<string>());
    await using var check = Database(); Assert.Equal(100, await check.AccessRequests.CountAsync(x => x.Status == "pending" && x.DeletedAt == null));
    Assert.False(await check.AccessRequests.AnyAsync(x => x.UserId == refused)); Assert.False(await check.Audit.AnyAsync(x => x.Target == refused));
  }
  [DatabaseFact]
  public async Task TierTitlesUseOnlyAllowedActiveMainModelsByPriorityThenCreationTime()
  {
    await using var f = await Fixture.Create(); var user = f.User("titles");
    var tier = await f.Tier(); var backupTier = await f.Tier(); var emptyTier = await f.Tier(); var forbiddenTier = await f.Tier();
    foreach (var allowed in new[] { tier, backupTier, emptyTier })
      await Object(await f.Admin.PostAsJsonAsync("/api/admin/grants", new { right_key = "chat.tier." + allowed, subject_type = "user", subject_id = user }), HttpStatusCode.Created);
    await using var db = Database(); var at = DateTimeOffset.UtcNow;
    void Add(string title, int modelTier, string role, int priority, DateTimeOffset created, bool removed = false) => db.Models.Add(new ModelEntry
    {
      Title = title,
      Purpose = "chat",
      Tier = modelTier,
      Role = role,
      Priority = priority,
      CreatedAt = created,
      DeletedAt = removed ? at : null,
      Location = "cloud",
      ApiType = "synthetic",
      ModelId = "synthetic-" + Guid.NewGuid(),
      EndpointUrl = "https://synthetic-model.invalid",
      RateLimitPerMinute = 1
    });
    Add("Older but lower priority", tier, "main", 200, at.AddMinutes(-10));
    Add("Earlier preferred main", tier, "main", 10, at.AddMinutes(-2));
    Add("Later preferred main", tier, "main", 10, at.AddMinutes(-1));
    Add("Backup is not a picker title", tier, "backup", 1, at.AddMinutes(-20));
    Add("Removed main", tier, "main", 1, at.AddMinutes(-30), true);
    Add("Backup-only tier", backupTier, "backup", 1, at.AddMinutes(-20));
    Add("Unallowed main", forbiddenTier, "main", 1, at.AddMinutes(-20));
    await db.SaveChangesAsync();
    var me = await Object(await f.Harness.GetAsync("/api/rights/me?user_id=" + user));
    var titles = me["chat_tier_titles"]!.AsObject(); Assert.Single(titles);
    Assert.Equal("Earlier preferred main", titles[tier.ToString(System.Globalization.CultureInfo.InvariantCulture)]!.GetValue<string>());
    Assert.False(titles.ContainsKey(backupTier.ToString(System.Globalization.CultureInfo.InvariantCulture)));
    Assert.False(titles.ContainsKey(emptyTier.ToString(System.Globalization.CultureInfo.InvariantCulture)));
    Assert.False(titles.ContainsKey(forbiddenTier.ToString(System.Globalization.CultureInfo.InvariantCulture)));
    Assert.DoesNotContain("https://synthetic-model.invalid", me.ToJsonString());
  }
  [DatabaseFact]
  public async Task BackfillIncludesOnlyPeopleAndActiveGrantsBeforeItsCutoff()
  {
    await using var f = await Fixture.Create(); await using var db = Database(true); await using var transaction = await db.Database.BeginTransactionAsync();
    var old = DateTimeOffset.UtcNow.AddDays(-1); var future = DateTimeOffset.UtcNow.AddDays(1);
    var person = f.User("old-person"); var granted = f.User("old-grant"); var excluded = f.User("future"); var removed = f.User("removed-grant");
    db.People.Add(new Person { UserId = person, FirstSeenAt = old, Name = "Synthetic Private Name", Email = "synthetic@backfill.invalid" });
    db.People.Add(new Person { UserId = excluded, FirstSeenAt = future });
    var right = "backfill." + Guid.NewGuid(); db.Rights.Add(new Right { Key = right, Source = "builtin" });
    foreach (var (user, created, deleted) in new[] { (granted, old, (DateTimeOffset?)null), (excluded, future, (DateTimeOffset?)null), (removed, old, (DateTimeOffset?)old) })
      db.Grants.Add(new Grant { RightKey = right, SubjectType = "user", SubjectId = user, CreatedAt = created, DeletedAt = deleted });
    await db.SaveChangesAsync(); await db.Database.ExecuteSqlRawAsync(ControlCentre.Migrations.AccessRequests.BackfillSql);
    foreach (var user in new[] { person, granted })
    {
      var row = await db.AccessRequests.SingleAsync(x => x.UserId == user); Assert.Equal("approved", row.Status); Assert.Equal("migration", row.DecidedBy);
      var audit = await db.Audit.SingleAsync(x => x.Target == user && x.Action == "access.approved");
      Assert.DoesNotContain("Synthetic Private Name", audit.Detail); Assert.DoesNotContain("synthetic@backfill.invalid", audit.Detail);
      Assert.True(await db.Outbox.AnyAsync(x => x.Key == audit.CorrelationId.ToString() && x.Topic == "audit.events"));
    }
    Assert.False(await db.AccessRequests.AnyAsync(x => x.UserId == excluded || x.UserId == removed)); await transaction.RollbackAsync();
  }
}
