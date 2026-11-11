// SPDX-License-Identifier: AGPL-3.0-only
using System.Net;
using System.Net.Http.Json;
using System.Text.Json.Nodes;
using Confluent.Kafka;
using ControlCentre.Platform;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Xunit;

namespace ControlCentre.Tests;

public sealed class ApprovalVisibilityTests
{
  private static CentreDb Database(bool owner = false) => new(new DbContextOptionsBuilder<CentreDb>().UseNpgsql(DatabaseConnections.Configure(TestSettings.Load()[owner ? "CC_TEST_DB_MIGRATE_CONNECTION" : "CC_TEST_DB_CONNECTION"])).Options);
  private static async Task Migrate() { await using var db = Database(true); await db.Database.MigrateAsync(); }
  private static async Task<JsonArray> Pending(HttpClient client)
  {
    var result = new JsonArray(); var before = "";
    while (true)
    {
      var page = (await client.GetFromJsonAsync<JsonArray>("/api/admin/approvals?status=pending&limit=200" + before))!;
      foreach (var row in page) result.Add(row!.DeepClone());
      if (page.Count < 200) return result;
      before = "&before=" + Uri.EscapeDataString(page[^1]!["created_at"] + "," + page[^1]!["id"]);
    }
  }
  private static int OverviewApprovals(JsonObject value) => value["needs_attention"]!.AsArray().Count(x => x!["kind"]!.GetValue<string>() == "approval");

  [DatabaseFact]
  public async Task HiddenRequestersStayOutOfListsAndBadgeCountsButExplicitAdminLookupsReturnThem()
  {
    await Migrate(); using var host = new Host(true); using var admin = host.Client();
    using var scope = host.Services.CreateScope(); var db = scope.ServiceProvider.GetRequiredService<CentreDb>();
    var consumer = scope.ServiceProvider.GetRequiredService<ApprovalConsumer>();
    var suffix = Guid.NewGuid().ToString("N");
    var hidden = new[] { "stage-check-" + suffix, "service-account-" + suffix, "synthetic-person-service-" + suffix, "synthetic-access-service-" + suffix };
    db.People.Add(new Person { UserId = hidden[2], IsServiceAccount = true });
    db.AccessRequests.Add(new AccessRequest { UserId = hidden[3], IsServiceAccount = true, Status = "approved" }); await db.SaveChangesAsync();
    var beforeCount = (await Pending(admin)).Count;
    var beforeOverview = OverviewApprovals((await admin.GetFromJsonAsync<JsonObject>("/api/admin/overview"))!);
    var rows = new List<Approval>();
    try
    {
      foreach (var user in hidden.Append("synthetic-human-" + suffix))
      {
        var envelope = RoutesWithoutDatabaseTests.Envelope(); envelope["user_id"] = user; envelope["producer"] = "ooh-stage-check";
        var record = new KafkaRecord("approvals.requested", envelope.ToJsonString(), new object());
        await consumer.Handle(record, TestContext.Current.CancellationToken); await consumer.Handle(record, TestContext.Current.CancellationToken);
        var eventId = Guid.Parse(envelope["event_id"]!.GetValue<string>());
        rows.Add(await db.Approvals.SingleAsync(x => x.RequestEventId == eventId));
      }
      var plain = (await admin.GetFromJsonAsync<JsonArray>("/api/admin/approvals?limit=200"))!;
      var pending = await Pending(admin);
      foreach (var user in hidden)
      {
        Assert.DoesNotContain(plain, x => x!["requester_user_id"]!.GetValue<string>() == user);
        Assert.DoesNotContain(pending, x => x!["requester_user_id"]!.GetValue<string>() == user);
      }
      Assert.Equal(beforeCount + 1, pending.Count);
      Assert.Contains(pending, x => x!["id"]!.GetValue<Guid>() == rows[^1].Id);
      var overview = (await admin.GetFromJsonAsync<JsonObject>("/api/admin/overview"))!;
      Assert.Equal(beforeOverview + 1, OverviewApprovals(overview));
      using var nonAdmin = host.Client("other");
      foreach (var row in rows)
      {
        var path = "/api/admin/approvals?correlation_id=" + row.CorrelationId;
        var correlated = (await admin.GetFromJsonAsync<JsonArray>(path))!;
        Assert.Single(correlated); Assert.Equal(row.Id, correlated[0]!["id"]!.GetValue<Guid>());
        Assert.Equal(row.RequesterUserId, correlated[0]!["requester_user_id"]!.GetValue<string>());
        var byId = (await admin.GetFromJsonAsync<JsonObject>("/api/admin/approvals/" + row.Id))!;
        Assert.Equal(row.Id, byId["id"]!.GetValue<Guid>());
        Assert.Equal(row.RequesterUserId, byId["requester_user_id"]!.GetValue<string>());
        Assert.Single((await admin.GetFromJsonAsync<JsonArray>(path + "&status=pending"))!);
        Assert.Equal(HttpStatusCode.Forbidden, (await nonAdmin.GetAsync(path)).StatusCode);
        Assert.Equal(HttpStatusCode.Forbidden, (await nonAdmin.GetAsync("/api/admin/approvals/" + row.Id)).StatusCode);
      }
      Assert.Empty((await admin.GetFromJsonAsync<JsonArray>("/api/admin/approvals?correlation_id=" + Guid.NewGuid()))!);
      Assert.Equal(HttpStatusCode.BadRequest, (await admin.GetAsync("/api/admin/approvals?correlation_id=bad")).StatusCode);
    }
    finally
    {
      foreach (var row in rows)
      {
        var response = await admin.PostAsJsonAsync("/api/admin/approvals/" + row.Id + "/decision", new { approved = false, note = "Synthetic visibility test finished" });
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
      }
    }
  }

  [DatabaseFact]
  public async Task DeadLetterDiagnosticsAndCountIncludeCheckRequester()
  {
    await Migrate(); using var host = new Host(true); using var admin = host.Client();
    var before = (await admin.GetFromJsonAsync<JsonObject>("/api/admin/dead-letters/count"))!["count"]!.GetValue<int>();
    await using var db = Database(); var envelope = RoutesWithoutDatabaseTests.Envelope(); envelope["type"] = "dlq.entry"; envelope["user_id"] = "stage-check-" + Guid.NewGuid();
    envelope["payload"] = new JsonObject { ["original_message"] = new JsonObject { ["user_id"] = envelope["user_id"]!.DeepClone() }.ToJsonString(), ["error"] = new JsonObject { ["code"] = "synthetic", ["message"] = "Synthetic diagnostic" } };
    var correlation = envelope["correlation_id"]!.GetValue<string>();
    var position = new ConsumeResult<string, string> { Topic = "dlq.approvals.requested", Partition = 0, Offset = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() };
    await new DeadLetterConsumer(db).Handle(new(position.Topic, envelope.ToJsonString(), position), TestContext.Current.CancellationToken);
    var list = (await admin.GetFromJsonAsync<JsonArray>("/api/admin/dead-letters?topic=dlq.approvals.requested&limit=200"))!;
    Assert.Contains(list, x => x!["correlation_id"]?.GetValue<string>() == correlation);
    Assert.Equal(before + 1, (await admin.GetFromJsonAsync<JsonObject>("/api/admin/dead-letters/count"))!["count"]!.GetValue<int>());
  }

  [DatabaseFact]
  public async Task TrailForwardsCheckAndServiceRequestFiltersAndReturnsTheirRowsUnchanged()
  {
    await Migrate(); Environment.SetEnvironmentVariable("CC_AUDIT_WRITER_URL", "http://audit.invalid:8080");
    try
    {
      using var host = new Host(true, "synthetic-service-secret"); using var admin = host.Client();
      foreach (var prefix in new[] { "stage-check-", "service-account-" })
      {
        var user = prefix + Guid.NewGuid(); var correlation = Guid.NewGuid();
        var expected = new[] { new { id = 1, user_id = user, correlation_id = correlation, actor = user, action = "approval.requested" } };
        host.Gateway.Answer = _ => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = JsonContent.Create(expected) });
        var query = "?correlation_id=" + correlation + "&user_id=" + user;
        var response = await admin.GetAsync("/api/admin/trail" + query); Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var result = (await response.Content.ReadFromJsonAsync<JsonArray>())!; Assert.Single(result); Assert.Equal(user, result[0]!["user_id"]!.GetValue<string>());
        Assert.Equal("/v1/trail", host.Gateway.GatewayUrl); Assert.Equal(query, host.Gateway.GatewayQuery);
        using var other = host.Client("other"); Assert.Equal(HttpStatusCode.Forbidden, (await other.GetAsync("/api/admin/trail" + query)).StatusCode);
      }
    }
    finally { Environment.SetEnvironmentVariable("CC_AUDIT_WRITER_URL", null); }
  }
}
