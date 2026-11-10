// SPDX-License-Identifier: AGPL-3.0-only
using System.Net;
using System.Net.Http.Json;
using System.Text.Json.Nodes;
using ControlCentre.Platform;
using Microsoft.EntityFrameworkCore;
using Xunit;

namespace ControlCentre.Tests;

public sealed class ModelTestRouteTests
{
  private const string Key = "fixture-provider-key-123456789";
  private static CentreDb Database(bool owner = false) => new(new DbContextOptionsBuilder<CentreDb>().UseNpgsql(DatabaseConnections.Configure(TestSettings.Load()[owner ? "CC_TEST_DB_MIGRATE_CONNECTION" : "CC_TEST_DB_CONNECTION"])).Options);
  private static async Task<ModelEntry> Entry(bool hasKey = true)
  {
    await using (var owner = Database(true)) await owner.Database.MigrateAsync();
    var row = new ModelEntry { Title = "Synthetic connection", Purpose = "classification", ModelId = "synthetic-model-" + Guid.NewGuid(), Role = "main", Location = "cloud", ApiType = "synthetic", EndpointUrl = "https://synthetic.invalid", RateLimitPerMinute = 1, TimeoutSeconds = 10 };
    if (hasKey) row.ApiKeyEncrypted = new ModelKeys(Convert.ToBase64String(new byte[32])).Encrypt(row.Id, Key);
    await using var db = Database(); db.Models.Add(row); await db.SaveChangesAsync(); return row;
  }
  [DatabaseFact]
  public async Task PublicTestRouteAuditsSuccessAndFailureWithoutSensitiveDetails()
  {
    var entry = await Entry(); using var host = new Host(true, "synthetic-service-secret"); using var admin = host.Client();
    Assert.Equal(8080, admin.BaseAddress!.Port);
    var path = $"/api/admin/models/{entry.Id}/test";
    var success = await admin.PostAsJsonAsync(path, new { });
    Assert.Equal(HttpStatusCode.OK, success.StatusCode);
    Assert.True((await success.Content.ReadFromJsonAsync<JsonObject>())!["ok"]!.GetValue<bool>());
    Assert.False(host.Gateway.GatewayBody!.ContainsKey("tier"));
    host.Gateway.Answer = _ => Task.FromResult(TestGatewayHttp.Error(503, "unavailable", 401, "synthetic-provider-detail " + Key));
    var failure = await admin.PostAsJsonAsync(path, new { });
    Assert.Equal(HttpStatusCode.OK, failure.StatusCode);
    var body = (await failure.Content.ReadFromJsonAsync<JsonObject>())!;
    Assert.False(body["ok"]!.GetValue<bool>()); Assert.Equal("key refused", body["reason"]!.GetValue<string>()); Assert.DoesNotContain(Key, body.ToJsonString());
    await using var db = Database();
    var rows = await db.Audit.Where(x => x.Action == "model.tested" && x.Target == entry.ModelId).ToListAsync();
    Assert.Equal(2, rows.Count);
    foreach (var audit in rows)
    {
      var detail = JsonNode.Parse(audit.Detail)!.AsObject();
      Assert.Equal(4, detail.Count); Assert.True(detail.ContainsKey("reason"));
      Assert.Equal(entry.Id.ToString(), detail["model_entry_id"]!.GetValue<string>());
      Assert.True(detail["duration_ms"]!.GetValue<long>() >= 0);
      Assert.DoesNotContain(Key, audit.Detail); Assert.DoesNotContain(entry.ApiKeyEncrypted!, audit.Detail);
      Assert.DoesNotContain("synthetic reply", audit.Detail); Assert.DoesNotContain("synthetic-provider-detail", audit.Detail);
      var envelope = await db.Outbox.SingleAsync(x => x.Key == audit.CorrelationId.ToString() && x.Topic == "audit.events");
      Assert.Equal("model.tested", JsonNode.Parse(envelope.Envelope)!["payload"]!["action"]!.GetValue<string>());
    }
    foreach (var line in host.Logs.Entries)
    { Assert.DoesNotContain(Key, line); Assert.DoesNotContain("synthetic reply", line); Assert.DoesNotContain("synthetic-provider-detail", line); }
  }
  [DatabaseFact]
  public async Task NoKeyMissingDeletedAndNonAdminRoutes()
  {
    var entry = await Entry(false); using var host = new Host(true); using var admin = host.Client();
    var path = $"/api/admin/models/{entry.Id}/test";
    var noKey = await admin.PostAsJsonAsync(path, new { });
    Assert.Equal(HttpStatusCode.Conflict, noKey.StatusCode);
    Assert.Equal("no_key", (await noKey.Content.ReadFromJsonAsync<JsonObject>())!["code"]!.GetValue<string>());
    Assert.Equal(0, host.Gateway.GatewayCalls);
    await using var db = Database();
    Assert.Single(await db.Audit.Where(x => x.Action == "model.tested" && x.Target == entry.ModelId).ToListAsync());
    Assert.Equal(HttpStatusCode.NotFound, (await admin.PostAsJsonAsync($"/api/admin/models/{Guid.NewGuid()}/test", new { })).StatusCode);
    foreach (var role in new[] { "harness", "gateway", "self", "other" })
    {
      using var client = host.Client(role);
      Assert.Equal(HttpStatusCode.Forbidden, (await client.PostAsJsonAsync(path, new { })).StatusCode);
    }
    Assert.Equal(HttpStatusCode.BadRequest, (await admin.PostAsJsonAsync(path, new { unexpected = true })).StatusCode);
    entry.DeletedAt = DateTimeOffset.UtcNow; db.Models.Attach(entry); db.Entry(entry).Property(x => x.DeletedAt).IsModified = true; await db.SaveChangesAsync();
    Assert.Equal(HttpStatusCode.NotFound, (await admin.PostAsJsonAsync(path, new { })).StatusCode);
  }
  [DatabaseFact]
  public async Task MissingOptionalCredentialsGivesAuditedFailureWithNullProviderFields()
  {
    var entry = await Entry(); using var host = new Host(true); using var admin = host.Client();
    var response = await admin.PostAsJsonAsync($"/api/admin/models/{entry.Id}/test", new { });
    Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    var body = (await response.Content.ReadFromJsonAsync<JsonObject>())!;
    Assert.Equal("the Control Centre has no service credentials", body["reason"]!.GetValue<string>());
    Assert.True(body.ContainsKey("provider_status")); Assert.Null(body["provider_status"]);
    Assert.True(body.ContainsKey("provider_message")); Assert.Null(body["provider_message"]);
    await using var db = Database(); Assert.Single(await db.Audit.Where(x => x.Action == "model.tested" && x.Target == entry.ModelId).ToListAsync());
  }
}
