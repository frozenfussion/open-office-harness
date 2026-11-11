// SPDX-License-Identifier: AGPL-3.0-only
using System.Net;
using System.Net.Http.Json;
using System.Text.Json.Nodes;
using ControlCentre.Platform;
using Microsoft.EntityFrameworkCore;
using Xunit;
namespace ControlCentre.Tests;

public sealed class OverviewDisplayTests
{
  private static CentreDb Database(bool owner = false) => new(new DbContextOptionsBuilder<CentreDb>().UseNpgsql(DatabaseConnections.Configure(TestSettings.Load()[owner ? "CC_TEST_DB_MIGRATE_CONNECTION" : "CC_TEST_DB_CONNECTION"])).Options);
  private static async Task Migrate() { await using var db = Database(true); await db.Database.MigrateAsync(); }
  [DatabaseFact]
  public async Task ActivePeopleComeFromLocalDaySightingsAndExcludeSyntheticAndServiceIdentities()
  {
    await Migrate(); var clock = new TestClock { Now = DateTimeOffset.Parse("2051-01-02T15:30:00Z") }; using var host = new Host(true) { Clock = clock }; using var admin = host.Client();
    await using var db = Database(); var suffix = Guid.NewGuid().ToString(); var start = DateTimeOffset.Parse("2051-01-01T16:00:00Z");
    var rows = new List<Person>
    {
      new() { UserId = "synthetic-start-" + suffix, LastSeenAt = start },
      new() { UserId = "synthetic-today-" + suffix, LastSeenAt = clock.Now },
      new() { UserId = "synthetic-yesterday-" + suffix, LastSeenAt = start.AddTicks(-10) },
      new() { UserId = "synthetic-next-day-" + suffix, LastSeenAt = start.AddDays(1) },
      new() { UserId = Guid.NewGuid().ToString(), IsServiceAccount = true, LastSeenAt = clock.Now },
      new() { UserId = "synthetic-removed-" + suffix, LastSeenAt = clock.Now, DeletedAt = clock.Now }
    };
    rows.AddRange(new[] { "stage-check-", "admin-test-", "title-", "service-account-" }.Select(prefix => new Person { UserId = prefix + suffix, LastSeenAt = clock.Now }));
    var baseline = (await admin.GetFromJsonAsync<JsonObject>("/api/admin/overview"))!["people_active_today"]!.GetValue<int>();
    var access = rows.Select(row => new AccessRequest { UserId = row.UserId, Status = "approved", IsServiceAccount = row.IsServiceAccount }).ToList();
    db.People.AddRange(rows); db.AccessRequests.AddRange(access); await db.SaveChangesAsync();
    try
    {
      var response = await admin.GetAsync("/api/admin/overview"); Assert.Equal(HttpStatusCode.OK, response.StatusCode);
      Assert.Equal("Asia/Kuala_Lumpur", Assert.Single(response.Headers.GetValues("X-Display-Time-Zone")));
      var overview = (await response.Content.ReadFromJsonAsync<JsonObject>())!;
      Assert.Equal(baseline + 2, overview["people_active_today"]!.GetValue<int>());
    }
    finally { foreach (var row in rows) row.DeletedAt = clock.Now; foreach (var row in access) row.DeletedAt = clock.Now; await db.SaveChangesAsync(); }
  }
  [DatabaseFact]
  public async Task PendingPersonSeenTodayIsNotCounted()
  {
    await Migrate(); var clock = new TestClock { Now = DateTimeOffset.Parse("2051-03-02T17:00:00Z") }; using var host = new Host(true) { Clock = clock }; using var admin = host.Client();
    await using var db = Database(); var suffix = Guid.NewGuid().ToString();
    var rows = new[] { "pending", "rejected", "approved", "deleted-access", "no-access" }.Select(status => new Person { UserId = "synthetic-" + status + "-" + suffix, LastSeenAt = clock.Now }).ToList();
    var access = rows.Take(4).Select((row, index) => new AccessRequest { UserId = row.UserId, Status = index < 2 ? new[] { "pending", "rejected" }[index] : "approved", DeletedAt = index == 3 ? clock.Now : null }).ToList();
    var before = (await admin.GetFromJsonAsync<JsonObject>("/api/admin/overview"))!;
    db.People.AddRange(rows); db.AccessRequests.AddRange(access); await db.SaveChangesAsync();
    try
    {
      var overview = (await admin.GetFromJsonAsync<JsonObject>("/api/admin/overview"))!;
      Assert.Equal(before["people_active_today"]!.GetValue<int>() + 1, overview["people_active_today"]!.GetValue<int>());
      Assert.Equal(before["people_approved"]!.GetValue<int>() + 1, overview["people_approved"]!.GetValue<int>());
    }
    finally { foreach (var row in rows) row.DeletedAt = clock.Now; foreach (var row in access) row.DeletedAt = clock.Now; await db.SaveChangesAsync(); }
  }
  [DatabaseFact]
  public async Task HarnessObservationRefreshesTheFirstSightingOnANewLocalDayWithinOneHour()
  {
    await Migrate(); var clock = new TestClock { Now = DateTimeOffset.Parse("2051-02-01T15:55:00Z") }; using var host = new Host(true) { Clock = clock }; using var harness = host.Client("harness"); using var admin = host.Client();
    var user = "synthetic-sighting-" + Guid.NewGuid();
    async Task Observe() => Assert.Equal(HttpStatusCode.OK, (await harness.PostAsJsonAsync("/api/access/observe", new { user_id = user, is_admin = false })).StatusCode);
    await Observe(); clock.Now = clock.Now.AddMinutes(10); await Observe();
    await using var db = Database(); var person = await db.People.SingleAsync(x => x.UserId == user);
    Assert.Equal(clock.Now, person.LastSeenAt); clock.Now = clock.Now.AddMinutes(5); await Observe(); await db.Entry(person).ReloadAsync(); Assert.Equal(clock.Now.AddMinutes(-5), person.LastSeenAt);
    var access = await db.AccessRequests.SingleAsync(x => x.UserId == user);
    Assert.Equal(HttpStatusCode.OK, (await admin.PostAsJsonAsync($"/api/admin/access-requests/{access.Id}/reject", new { })).StatusCode);
    person.DeletedAt = clock.Now; await db.SaveChangesAsync();
  }
  [DatabaseFact]
  public async Task DeadLetterAttentionUsesNewestReceivedTimeInsteadOfOverviewRequestTime()
  {
    await Migrate(); await using var db = Database(); var latest = await db.DeadLetters.Select(x => (DateTimeOffset?)x.ReceivedAt).MaxAsync() ?? DateTimeOffset.UtcNow;
    var clock = new TestClock { Now = latest.AddDays(3) }; var newest = clock.Now.AddMinutes(-50);
    foreach (var at in new[] { clock.Now.AddHours(-25), clock.Now.AddHours(-2), newest }) db.DeadLetters.Add(new DeadLetter { Topic = "dlq.approvals.requested", Partition = 0, Offset = at.ToUnixTimeMilliseconds(), ReceivedAt = at, ErrorCode = "synthetic", ErrorMessage = "Synthetic error", OriginalMessage = "Synthetic input" });
    await db.SaveChangesAsync(); using var host = new Host(true) { Clock = clock }; using var admin = host.Client();
    var overview = (await admin.GetFromJsonAsync<JsonObject>("/api/admin/overview"))!;
    var item = overview["needs_attention"]!.AsArray().Single(x => x!["kind"]!.GetValue<string>() == "dead_letter")!;
    Assert.Equal(newest, item["at"]!.GetValue<DateTimeOffset>()); Assert.Equal("2 in the last 24 hours", item["detail"]!.GetValue<string>());
  }
  [DatabaseFact]
  public async Task TrailDisplaysKnownNamesThenEmailAndPreservesIdsForHover()
  {
    await Migrate(); await using var db = Database(); var suffix = Guid.NewGuid().ToString(); var named = "synthetic-name-" + suffix; var emailed = "synthetic-email-" + suffix; var unknown = "synthetic-unknown-" + suffix;
    db.People.Add(new Person { UserId = named, Name = "Synthetic Person", Email = "synthetic@test.invalid" });
    db.AccessRequests.Add(new AccessRequest { UserId = emailed, Email = "synthetic-access@test.invalid", Status = "approved" }); await db.SaveChangesAsync();
    Environment.SetEnvironmentVariable("CC_AUDIT_WRITER_URL", "http://audit.invalid:8080");
    try
    {
      using var host = new Host(true, "synthetic-service-secret"); using var admin = host.Client();
      host.Gateway.Answer = _ => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = JsonContent.Create(new[] { new { id = 1, user_id = named }, new { id = 2, user_id = emailed }, new { id = 3, user_id = unknown } }) });
      var trail = (await admin.GetFromJsonAsync<JsonArray>("/api/admin/trail"))!;
      Assert.Equal("Synthetic Person", trail[0]!["person"]!.GetValue<string>()); Assert.Equal(named, trail[0]!["user_id"]!.GetValue<string>());
      Assert.Equal("synthetic-access@test.invalid", trail[1]!["person"]!.GetValue<string>()); Assert.Equal(unknown, trail[2]!["person"]!.GetValue<string>());
    }
    finally { Environment.SetEnvironmentVariable("CC_AUDIT_WRITER_URL", null); }
  }
}
