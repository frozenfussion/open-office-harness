// SPDX-License-Identifier: AGPL-3.0-only
using System.Net;
using System.Net.Http.Json;
using System.Text.Json.Nodes;
using ControlCentre.Platform;
using Microsoft.EntityFrameworkCore;
using Npgsql;
using Xunit;

namespace ControlCentre.Tests;

public sealed class TierRequestTests
{
  private static CentreDb Database(bool owner = false) => new(new DbContextOptionsBuilder<CentreDb>().UseNpgsql(DatabaseConnections.Configure(TestSettings.Load()[owner ? "CC_TEST_DB_MIGRATE_CONNECTION" : "CC_TEST_DB_CONNECTION"])).Options);
  private sealed class Fixture : IAsyncDisposable
  {
    public TestClock Clock { get; } = new();
    public Host Host { get; }
    public HttpClient Admin { get; }
    public HttpClient Harness { get; }
    public string User { get; } = "tier-test-" + Guid.NewGuid();
    public List<int> Tiers { get; } = [];
    private Fixture() { Host = new(true) { Clock = Clock }; Admin = Host.Client(); Harness = Host.Client("harness"); }
    public static async Task<Fixture> Create(bool approved = true)
    {
      await using var db = Database(true); await db.Database.MigrateAsync(); var f = new Fixture();
      if (approved) { db.AccessRequests.Add(new AccessRequest { UserId = f.User, Status = "approved" }); await db.SaveChangesAsync(); }
      return f;
    }
    public async Task<int> Model(string role = "main", string? off = null, int priority = 100, string title = "Synthetic tier")
    {
      var tier = System.Security.Cryptography.RandomNumberGenerator.GetInt32(100000, int.MaxValue); Tiers.Add(tier);
      await using var db = Database(); db.Rights.Add(new Right { Key = "chat.tier." + tier, Source = "tier" });
      db.Models.Add(Entry(tier, role, off, priority, title)); await db.SaveChangesAsync(); return tier;
    }
    public Task<HttpResponseMessage> Request(int tier, string? reason = null) => Harness.PostAsJsonAsync("/api/tier-requests", new { user_id = User, tier, reason });
    public Task<JsonObject> Me() => Object(Harness.GetAsync("/api/rights/me?user_id=" + User));
    public async ValueTask DisposeAsync()
    {
      // Keep historical requests and grants; hide only this fixture's models from later picker tests.
      await using var db = Database(); foreach (var model in await db.Models.Where(x => Tiers.Contains(x.Tier ?? 0) && x.DeletedAt == null).ToListAsync()) model.DeletedAt = DateTimeOffset.UtcNow;
      await db.SaveChangesAsync(); Admin.Dispose(); Harness.Dispose(); await Host.DisposeAsync();
    }
  }
  private static ModelEntry Entry(int tier, string role = "main", string? off = null, int priority = 100, string title = "Synthetic tier") => new()
  { Tier = tier, Purpose = "chat", Title = title, Role = role, Location = "cloud", ApiType = "synthetic", ModelId = "synthetic-" + Guid.NewGuid(), EndpointUrl = "https://synthetic.invalid", RateLimitPerMinute = 1, RequestSettingsThinkingOff = off, Priority = priority };
  private static async Task<JsonObject> Object(Task<HttpResponseMessage> answer, HttpStatusCode status = HttpStatusCode.OK)
  { var response = await answer; Assert.Equal(status, response.StatusCode); return (await response.Content.ReadFromJsonAsync<JsonObject>())!; }
  private static async Task Code(Task<HttpResponseMessage> answer, HttpStatusCode status, string code) => Assert.Equal(code, (await Object(answer, status))["code"]!.GetValue<string>());
  private static JsonNode? Choice(JsonObject me, int tier) => me["requestable_tiers"]!.AsArray().SingleOrDefault(x => x!["tier"]!.GetValue<int>() == tier);
  private static string Key(int tier) => tier.ToString(System.Globalization.CultureInfo.InvariantCulture);

  [DatabaseFact]
  public async Task ThinkingSettingsRoundTripNullObjectAndOmittedAndRejectNonObjects()
  {
    await using var f = await Fixture.Create(); var tier = await f.Model(); await using var db = Database(); var entry = await db.Models.SingleAsync(x => x.Tier == tier);
    var input = new JsonObject { ["purpose"] = "chat", ["tier"] = tier, ["role"] = "main", ["location"] = "cloud", ["api_type"] = "synthetic", ["endpoint_url"] = "https://synthetic.invalid", ["model_id"] = entry.ModelId, ["rate_limit_per_minute"] = 1, ["daily_budget"] = 0 };
    var path = "/api/admin/models/" + entry.Id;
    var initial = await Object(f.Admin.GetAsync(path)); Assert.True(initial.ContainsKey("request_settings_thinking_off")); Assert.Null(initial["request_settings_thinking_off"]);
    foreach (var bad in new JsonNode[] { new JsonArray(), JsonValue.Create(true)!, JsonValue.Create(3)!, JsonValue.Create("text")! })
    { input["request_settings_thinking_off"] = bad; await Code(f.Admin.PutAsJsonAsync(path, input), HttpStatusCode.BadRequest, "invalid_input"); }
    input["request_settings_thinking_off"] = new JsonObject { ["thinking"] = new JsonObject { ["type"] = "disabled" } };
    Assert.Equal("disabled", (await Object(f.Admin.PutAsJsonAsync(path, input)))["request_settings_thinking_off"]!["thinking"]!["type"]!.GetValue<string>());
    input.Remove("request_settings_thinking_off"); Assert.NotNull((await Object(f.Admin.PutAsJsonAsync(path, input)))["request_settings_thinking_off"]);
    using var gateway = f.Host.Client("gateway", port: 8081);
    var registry = (await gateway.GetFromJsonAsync<JsonArray>("/api/models?purpose=chat&tier=" + tier))!;
    Assert.NotNull(registry.Single()!["request_settings_thinking_off"]);
    input["request_settings_thinking_off"] = new JsonObject(); Assert.Empty((await Object(f.Admin.PutAsJsonAsync(path, input)))["request_settings_thinking_off"]!.AsObject());
    input["request_settings_thinking_off"] = null; Assert.Null((await Object(f.Admin.PutAsJsonAsync(path, input)))["request_settings_thinking_off"]);
    foreach (var value in new[] { "[]", "true", "3", "\"text\"", "null" })
    {
      await using var tx = await db.Database.BeginTransactionAsync();
      var error = await Assert.ThrowsAsync<PostgresException>(() => db.Database.ExecuteSqlInterpolatedAsync($"UPDATE model_entries SET request_settings_thinking_off={value}::jsonb WHERE id={entry.Id}"));
      Assert.Equal("23514", error.SqlState); await tx.RollbackAsync();
    }
  }
  [DatabaseFact]
  public async Task ChoicesShareMainSelectionAndExcludeOwnedEveryoneBackupAndReservedTiers()
  {
    await using var f = await Fixture.Create(); var tier = await f.Model(off: "{}", priority: 10, title: "Chosen main");
    var noSwitch = await f.Model(); var backup = await f.Model("backup", "{}"); var everyone = await f.Model(); var requestable = await f.Model(off: "{}");
    await using var db = Database(); db.Models.Add(Entry(tier, off: null, priority: 20, title: "Other main")); db.Models.Add(Entry(tier, "backup", null, 1));
    foreach (var n in new[] { tier, noSwitch, backup }) db.Grants.Add(new Grant { SubjectType = "user", SubjectId = f.User, RightKey = "chat.tier." + n });
    var grant = new Grant { SubjectType = "everyone", RightKey = "chat.tier." + everyone }; db.Grants.Add(grant);
    await db.SaveChangesAsync();
    try
    {
      var me = await f.Me(); Assert.Equal("Chosen main", me["chat_tier_titles"]![Key(tier)]!.GetValue<string>());
      Assert.True(me["chat_tier_thinking_switch"]![Key(tier)]!.GetValue<bool>()); Assert.False(me["chat_tier_thinking_switch"]![Key(noSwitch)]!.GetValue<bool>());
      Assert.False(me["chat_tier_thinking_switch"]!.AsObject().ContainsKey(Key(backup)));
      foreach (var excluded in new[] { tier, noSwitch, backup, everyone, 99 }) Assert.Null(Choice(me, excluded));
      Assert.NotNull(Choice(me, requestable)); Assert.True(Choice(me, requestable)!.AsObject().ContainsKey("requested")); Assert.Null(Choice(me, requestable)!["requested"]);
      Assert.DoesNotContain("request_settings", me.ToJsonString()); Assert.DoesNotContain("synthetic.invalid", me.ToJsonString());
    }
    finally { grant.DeletedAt = DateTimeOffset.UtcNow; await db.SaveChangesAsync(); }
  }
  [DatabaseFact]
  public async Task RequestsValidateCallerApprovalEligibilityAndReasonWithoutAuditingOrLoggingIt()
  {
    await using var f = await Fixture.Create(false); var tier = await f.Model();
    foreach (var role in new[] { "admin", "self", "gateway", "other" })
    { using var client = f.Host.Client(role); await Code(client.PostAsJsonAsync("/api/tier-requests", new { user_id = f.User, tier }), HttpStatusCode.Forbidden, "forbidden"); }
    await Code(f.Request(tier), HttpStatusCode.Forbidden, "not_approved");
    var empty = await f.Me(); Assert.Empty(empty["chat_tier_thinking_switch"]!.AsObject()); Assert.Empty(empty["requestable_tiers"]!.AsArray());
    await using var db = Database(); db.AccessRequests.Add(new AccessRequest { UserId = f.User, Status = "approved" }); await db.SaveChangesAsync();
    foreach (var n in new[] { 0, -1, 99, int.MaxValue }) await Code(f.Request(n), HttpStatusCode.BadRequest, "tier_not_requestable");
    await Code(f.Request(tier, new string('x', 301)), HttpStatusCode.BadRequest, "invalid_input");
    foreach (var body in new[] { "{}", "{\"user_id\":\"u\",\"tier\":1,\"extra\":true}", "{\"user_id\":\"u\",\"tier\":\"1\"}", "{\"user_id\":\"u\",\"tier\":1,\"reason\":3}" })
      await Code(RoutesWithoutDatabaseTests.Send(f.Harness, "POST", "/api/tier-requests", body), HttpStatusCode.BadRequest, "invalid_input");
    var reason = "<script>Synthetic private model request</script>";
    var requested = await Object(f.Request(tier, "  " + reason + "  "), HttpStatusCode.Created); Assert.Equal("pending", requested["status"]!.GetValue<string>()); Assert.Equal(2, requested.Count);
    Assert.Equal("pending", Choice(await f.Me(), tier)!["requested"]!.GetValue<string>());
    await Code(f.Request(tier), HttpStatusCode.Conflict, "already_requested");
    var row = await db.TierRequests.SingleAsync(x => x.UserId == f.User); Assert.Equal(reason, row.Reason);
    await Object(f.Admin.PostAsJsonAsync($"/api/admin/tier-requests/{row.Id}/reject", new { }));
    foreach (var audit in await db.Audit.Where(x => x.Target == f.User && x.Action.StartsWith("tier.")).ToListAsync())
    {
      Assert.DoesNotContain(reason, audit.Detail); Assert.DoesNotContain("reason", audit.Detail);
      var envelope = await db.Outbox.SingleAsync(x => x.Key == audit.CorrelationId.ToString() && x.Topic == "audit.events"); Assert.DoesNotContain(reason, envelope.Envelope);
    }
    Assert.DoesNotContain(f.Host.Logs.Entries, x => x.Contains(reason, StringComparison.Ordinal));
  }
  [DatabaseFact]
  public async Task RejectedRequestsRetryExactlyAfterSevenDaysAndConcurrentDuplicatesAreRefused()
  {
    await using var f = await Fixture.Create(); var tier = await f.Model();
    var results = await Task.WhenAll(f.Request(tier), f.Request(tier)); Assert.Equal(new[] { HttpStatusCode.Created, HttpStatusCode.Conflict }, results.Select(x => x.StatusCode).Order());
    await using var db = Database(); var row = await db.TierRequests.SingleAsync(x => x.UserId == f.User);
    await Object(f.Admin.PostAsJsonAsync($"/api/admin/tier-requests/{row.Id}/reject", new { }));
    Assert.Equal("rejected", Choice(await f.Me(), tier)!["requested"]!.GetValue<string>());
    f.Clock.Now = f.Clock.Now.AddDays(7).AddTicks(-10);
    var early = await Object(f.Request(tier), HttpStatusCode.Conflict);
    Assert.Equal("too_soon", early["code"]!.GetValue<string>());
    Assert.Equal("You can ask for this model again 7 days after the last answer", early["message"]!.GetValue<string>());
    f.Clock.Now = f.Clock.Now.AddTicks(10); await Object(f.Request(tier), HttpStatusCode.Created);
    Assert.Equal(2, await db.TierRequests.CountAsync(x => x.UserId == f.User));
  }
  [DatabaseFact]
  public async Task PendingCapIsAtomicAtTwentyAndOnePendingPerTierIsDatabaseEnforced()
  {
    await using var f = await Fixture.Create(); var first = await f.Model(); var second = await f.Model();
    await using var db = Database();
    for (var n = 1; n <= 19; n++) db.TierRequests.Add(new TierRequest { UserId = f.User, Tier = n });
    await db.SaveChangesAsync(); var results = await Task.WhenAll(f.Request(first), f.Request(second));
    Assert.Equal(new[] { HttpStatusCode.Created, HttpStatusCode.TooManyRequests }, results.Select(x => x.StatusCode).Order());
    Assert.Equal(20, await db.TierRequests.CountAsync(x => x.UserId == f.User && x.Status == "pending"));
    await using var tx = await db.Database.BeginTransactionAsync(); db.TierRequests.Add(new TierRequest { UserId = f.User, Tier = 1 });
    var error = await Assert.ThrowsAsync<DbUpdateException>(() => db.SaveChangesAsync()); Assert.Equal("23505", ((PostgresException)error.InnerException!).SqlState); await tx.RollbackAsync();
  }
  [DatabaseFact]
  public async Task AdminApprovesReusingGrantRejectsAndRefusesDecidedRevokedAndMissingRequests()
  {
    await using var f = await Fixture.Create(); var tier = await f.Model(); var second = await f.Model();
    var row = await Object(f.Request(tier), HttpStatusCode.Created); var id = row["id"]!.GetValue<string>(); var path = "/api/admin/tier-requests/" + id;
    await using var db = Database(); db.Grants.Add(new Grant { SubjectType = "user", SubjectId = f.User, RightKey = "chat.tier." + tier }); await db.SaveChangesAsync();
    var approved = await Object(f.Admin.PostAsJsonAsync(path + "/approve", new { })); Assert.Equal("approved", approved["status"]!.GetValue<string>());
    Assert.Single(await db.Grants.Where(x => x.SubjectId == f.User && x.RightKey == "chat.tier." + tier && x.DeletedAt == null).ToListAsync());
    Assert.Null(Choice(await f.Me(), tier));
    foreach (var action in new[] { "approve", "reject" }) await Code(f.Admin.PostAsJsonAsync(path + "/" + action, new { }), HttpStatusCode.Conflict, "conflict");
    row = await Object(f.Request(second), HttpStatusCode.Created); path = "/api/admin/tier-requests/" + row["id"]!.GetValue<string>();
    var access = await db.AccessRequests.SingleAsync(x => x.UserId == f.User); await Object(f.Admin.PostAsJsonAsync($"/api/admin/access-requests/{access.Id}/revoke", new { }));
    foreach (var action in new[] { "approve", "reject" }) await Code(f.Admin.PostAsJsonAsync(path + "/" + action, new { }), HttpStatusCode.Conflict, "not_approved");
    await db.Entry(access).ReloadAsync(); access.Status = "approved"; await db.SaveChangesAsync();
    approved = await Object(f.Admin.PostAsJsonAsync(path + "/approve", new { })); Assert.Equal("approved", approved["status"]!.GetValue<string>());
    Assert.True(await db.Grants.AnyAsync(x => x.SubjectId == f.User && x.RightKey == "chat.tier." + second && x.DeletedAt == null));
    await Code(f.Admin.PostAsJsonAsync($"/api/admin/tier-requests/{Guid.NewGuid()}/reject", new { }), HttpStatusCode.NotFound, "not_found");
  }
  [DatabaseFact]
  public async Task AdminListsPageFilterCountHideCheckUsersAndFallBackToUserId()
  {
    await using var f = await Fixture.Create(); var tier = await f.Model(); await using var db = Database();
    var hidden = new TierRequest { UserId = "stage-check-" + Guid.NewGuid(), Tier = tier }; db.TierRequests.Add(hidden);
    var fallback = new TierRequest { UserId = "tier-fallback-" + Guid.NewGuid(), Tier = tier }; db.TierRequests.Add(fallback);
    var profile = await db.AccessRequests.SingleAsync(x => x.UserId == f.User); profile.Name = "Synthetic applicant"; profile.Email = "synthetic@tier.invalid";
    await db.SaveChangesAsync(); await Object(f.Request(tier), HttpStatusCode.Created);
    var list = (await f.Admin.GetFromJsonAsync<JsonArray>("/api/admin/tier-requests?limit=200"))!;
    Assert.DoesNotContain(list, x => x!["user_id"]!.GetValue<string>().StartsWith("stage-check-", StringComparison.Ordinal));
    var found = list.Single(x => x!["user_id"]!.GetValue<string>() == f.User)!; Assert.Equal(profile.Name, found["name"]!.GetValue<string>()); Assert.Equal(profile.Email, found["email"]!.GetValue<string>());
    var absent = list.Single(x => x!["user_id"]!.GetValue<string>() == fallback.UserId)!; Assert.Equal(fallback.UserId, absent["name"]!.GetValue<string>()); Assert.Equal(fallback.UserId, absent["email"]!.GetValue<string>());
    var first = (await f.Admin.GetFromJsonAsync<JsonArray>("/api/admin/tier-requests?limit=2"))!;
    var next = (await f.Admin.GetFromJsonAsync<JsonArray>("/api/admin/tier-requests?limit=200&after=" + first.Last()!["id"]!.GetValue<string>()))!;
    Assert.DoesNotContain(next, x => first.Any(p => p!["id"]!.GetValue<string>() == x!["id"]!.GetValue<string>()));
    var count = await Object(f.Admin.GetAsync("/api/admin/tier-requests/count?status=pending")); Assert.Equal(await db.TierRequests.CountAsync(x => x.Status == "pending" && x.DeletedAt == null && !x.UserId.StartsWith("stage-check-")), count["count"]!.GetValue<int>());
    foreach (var query in new[] { "?status=bad", "?limit=201", "?after=bad" }) await Code(f.Admin.GetAsync("/api/admin/tier-requests" + query), HttpStatusCode.BadRequest, "invalid_input");
    foreach (var query in new[] { "", "?status=approved" }) await Code(f.Admin.GetAsync("/api/admin/tier-requests/count" + query), HttpStatusCode.BadRequest, "invalid_input");
    await Code(f.Admin.PostAsJsonAsync($"/api/admin/tier-requests/{hidden.Id}/reject", new { }), HttpStatusCode.NotFound, "not_found");
    await Object(f.Admin.PostAsJsonAsync($"/api/admin/tier-requests/{found["id"]!.GetValue<string>()}/reject", new { }));
    var rejected = (await f.Admin.GetFromJsonAsync<JsonArray>("/api/admin/tier-requests?status=rejected&limit=200"))!; Assert.Contains(rejected, x => x!["user_id"]!.GetValue<string>() == f.User);
    var approved = (await f.Admin.GetFromJsonAsync<JsonArray>("/api/admin/tier-requests?status=approved&limit=200"))!; Assert.DoesNotContain(approved, x => x!["user_id"]!.GetValue<string>() == f.User);
  }
}
