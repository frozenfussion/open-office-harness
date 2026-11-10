// SPDX-License-Identifier: AGPL-3.0-only
using System.Net;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using ControlCentre.Platform;
using Microsoft.EntityFrameworkCore;
using Xunit;

namespace ControlCentre.Tests;

public sealed class StageTwoTests
{
  [Fact]
  public void EncryptionRoundTripTamperingWrongRowAndWrongKey()
  {
    var keys = new ModelKeys(Convert.ToBase64String(RandomNumberGenerator.GetBytes(32)));
    var id = Guid.NewGuid(); var plaintext = "synthetic-" + Guid.NewGuid();
    var encrypted = keys.Encrypt(id, plaintext);
    Assert.Equal(plaintext, keys.Decrypt(id, encrypted));
    Assert.DoesNotContain(plaintext, encrypted);
    Assert.Throws<ApiException>(() => keys.Decrypt(Guid.NewGuid(), encrypted));
    var parts = encrypted.Split(':'); var tag = Convert.FromBase64String(parts[3]); tag[0] ^= 1;
    parts[3] = Convert.ToBase64String(tag);
    Assert.Throws<ApiException>(() => keys.Decrypt(id, string.Join(':', parts)));
    var wrong = new ModelKeys(Convert.ToBase64String(RandomNumberGenerator.GetBytes(32)));
    var error = Assert.Throws<ApiException>(() => wrong.Decrypt(id, encrypted));
    Assert.DoesNotContain(encrypted, error.Message);
  }
  [Theory]
  [InlineData(null)]
  [InlineData("")]
  [InlineData("not-base64")]
  [InlineData("YWJj")]
  public void InvalidEncryptionConfigurationRefused(string? value)
  {
    var error = Assert.Throws<InvalidOperationException>(() => new ModelKeys(value));
    Assert.Equal("CC_KEY_ENCRYPTION_KEY must contain 32 bytes encoded as base64", error.Message);
  }
  [Theory]
  [InlineData("/api/models?purpose=chat&tier=1")]
  [InlineData("/api/models/00000000-0000-0000-0000-000000000001/key")]
  public async Task InternalRoutesNotPublicAndRefuseOtherCallers(string path)
  {
    using var host = new Host();
    foreach (var role in new[] { "admin", "harness", "gateway" })
    {
      using var client = host.Client(role, port: 8081);
      Assert.Equal(HttpStatusCode.NotFound, (await client.GetAsync("http://localhost:8080" + path, TestContext.Current.CancellationToken)).StatusCode);
      if (role != "gateway") Assert.Equal(HttpStatusCode.Forbidden, (await client.GetAsync(path, TestContext.Current.CancellationToken)).StatusCode);
    }
  }
  private static CentreDb Database(bool owner = false) => new(new DbContextOptionsBuilder<CentreDb>()
    .UseNpgsql(DatabaseConnections.Configure(TestSettings.Load()[owner ? "CC_TEST_DB_MIGRATE_CONNECTION" : "CC_TEST_DB_CONNECTION"])).Options);
  private static JsonObject Input() => new()
  {
    ["purpose"] = "stage-two-" + Guid.NewGuid(),
    ["title"] = "Synthetic model",
    ["role"] = "main",
    ["location"] = "cloud",
    ["api_type"] = "synthetic",
    ["endpoint_url"] = "https://synthetic.invalid",
    ["model_id"] = "synthetic-" + Guid.NewGuid(),
    ["rate_limit_per_minute"] = 10,
    ["daily_budget"] = 0,
    ["priority"] = 7,
    ["timeout_seconds"] = 30,
    ["input_price_per_million"] = 1.25m,
    ["output_price_per_million"] = 2.5m,
    ["request_settings"] = new JsonObject { ["extra"] = true }
  };
  [DatabaseFact]
  public async Task KeysNeverInViewsOrAuditAndFollowTheirAddress()
  {
    await using (var owner = Database(true)) await owner.Database.MigrateAsync();
    using var host = new Host(true); using var admin = host.Client(); using var gateway = host.Client("gateway", port: 8081);
    var input = Input(); var key = "synthetic-key-" + Guid.NewGuid(); input["api_key"] = key;
    var response = await admin.PostAsJsonAsync("/api/admin/models", input);
    Assert.Equal(HttpStatusCode.Created, response.StatusCode);
    var result = (await response.Content.ReadFromJsonAsync<JsonObject>())!;
    var id = result["model_entry_id"]!.GetValue<string>();
    Assert.True(result["has_key"]!.GetValue<bool>()); Assert.DoesNotContain(key, result.ToJsonString());
    Assert.Equal(key, (await gateway.GetFromJsonAsync<JsonObject>($"/api/models/{id}/key"))!["api_key"]!.GetValue<string>());
    Assert.DoesNotContain(key, await admin.GetStringAsync("/api/admin/models?limit=200"));
    Assert.DoesNotContain(key, await gateway.GetStringAsync("/api/models?purpose=" + input["purpose"]!.GetValue<string>()));
    await using var db = Database();
    var row = await db.Models.FindAsync(Guid.Parse(id));
    var encrypted = row!.ApiKeyEncrypted!;
    input.Remove("api_key"); input["endpoint_url"] = "https://changed.invalid";
    var changed = await admin.PutAsJsonAsync("/api/admin/models/" + id, input);
    Assert.Equal(HttpStatusCode.OK, changed.StatusCode);
    Assert.Equal(HttpStatusCode.NotFound, (await gateway.GetAsync($"/api/models/{id}/key")).StatusCode);
    input["api_key"] = key; input["api_type"] = "another-synthetic";
    Assert.Equal(HttpStatusCode.OK, (await admin.PutAsJsonAsync("/api/admin/models/" + id, input)).StatusCode);
    Assert.Equal(key, (await gateway.GetFromJsonAsync<JsonObject>($"/api/models/{id}/key"))!["api_key"]!.GetValue<string>());
    input["api_key"] = "";
    Assert.Equal(HttpStatusCode.OK, (await admin.PutAsJsonAsync("/api/admin/models/" + id, input)).StatusCode);
    Assert.Equal(HttpStatusCode.NotFound, (await gateway.GetAsync($"/api/models/{id}/key")).StatusCode);
    input["api_key"] = key;
    await admin.PutAsJsonAsync("/api/admin/models/" + id, input);
    Assert.Equal(HttpStatusCode.OK, (await admin.DeleteAsync("/api/admin/models/" + id)).StatusCode);
    var audits = await db.Audit.Where(x => x.Target == input["model_id"]!.GetValue<string>()).Select(x => x.Detail).ToListAsync();
    var auditView = await admin.GetStringAsync("/api/admin/audit?limit=200&target=" + input["model_id"]!.GetValue<string>());
    Assert.DoesNotContain(key, auditView); Assert.DoesNotContain(encrypted, auditView);
    Assert.NotEmpty(audits);
    Assert.Contains(host.Logs.Entries, x => x.Contains("Model key read for entry", StringComparison.Ordinal));
    foreach (var log in host.Logs.Entries) { Assert.DoesNotContain(key, log); Assert.DoesNotContain(encrypted, log); }
    foreach (var detail in audits) { Assert.DoesNotContain(key, detail); Assert.DoesNotContain(encrypted, detail); }
    Assert.Contains(audits, x => JsonNode.Parse(x)?["api_key"]?.GetValue<string>() == "set");
    Assert.Contains(audits, x => JsonNode.Parse(x)?["api_key"]?.GetValue<string>() == "removed");
  }
  [DatabaseFact]
  public async Task NewFieldsValidationOldRowsAndDuplicateModels()
  {
    await using (var owner = Database(true)) await owner.Database.MigrateAsync();
    using var host = new Host(true); using var admin = host.Client();
    var input = Input();
    foreach (var (field, value) in new (string, JsonNode?)[] { ("priority", 0), ("priority", 1001), ("timeout_seconds", 9), ("timeout_seconds", 901), ("input_price_per_million", -1), ("output_price_per_million", -1), ("request_settings", new JsonArray()), ("request_settings", null), ("api_key", new string('x', 4097)) })
    {
      var invalid = (JsonObject)input.DeepClone(); invalid[field] = value?.DeepClone();
      Assert.Equal(HttpStatusCode.BadRequest, (await admin.PostAsJsonAsync("/api/admin/models", invalid)).StatusCode);
    }
    foreach (var field in new[] { "title", "priority", "timeout_seconds", "input_price_per_million", "output_price_per_million", "request_settings" }) input.Remove(field);
    for (var i = 0; i < 2; i++)
    {
      var response = await admin.PostAsJsonAsync("/api/admin/models", input);
      Assert.Equal(HttpStatusCode.Created, response.StatusCode);
      var result = (await response.Content.ReadFromJsonAsync<JsonObject>())!;
      Assert.False(result["has_key"]!.GetValue<bool>());
      Assert.Equal(120, result["timeout_seconds"]!.GetValue<int>());
      Assert.Equal(100, result["priority"]!.GetValue<int>());
    }
  }
  [DatabaseFact]
  public async Task DatabaseEnforcesModelRangesForOwnerAndApplication()
  {
    await using (var owner = Database(true)) await owner.Database.MigrateAsync();
    foreach (var owner in new[] { false, true })
      foreach (var invalid in new[] { "priority-low", "priority-high", "timeout-low", "timeout-high", "settings-array", "settings-null", "settings-scalar" })
      {
        await using var db = Database(owner);
        await using var transaction = await db.Database.BeginTransactionAsync();
        var row = new ModelEntry { Purpose = "synthetic-constraint", Role = "main", Location = "cloud", ApiType = "synthetic", EndpointUrl = "https://synthetic.invalid", ModelId = "synthetic", RateLimitPerMinute = 1 };
        db.Models.Add(row);
        await db.SaveChangesAsync();
        switch (invalid)
        {
          case "priority-low": row.Priority = 0; break;
          case "priority-high": row.Priority = 1001; break;
          case "timeout-low": row.TimeoutSeconds = 9; break;
          case "timeout-high": row.TimeoutSeconds = 901; break;
          case "settings-array": row.RequestSettings = "[]"; break;
          case "settings-null": row.RequestSettings = "null"; break;
          case "settings-scalar": row.RequestSettings = "42"; break;
        }
        // Direct SQL must exercise zero values rather than EF's generated default sentinel.
        var postgres = await Assert.ThrowsAsync<Npgsql.PostgresException>(() => invalid.StartsWith("priority", StringComparison.Ordinal)
          ? db.Database.ExecuteSqlInterpolatedAsync($"UPDATE model_entries SET priority = {row.Priority} WHERE id = {row.Id}")
          : invalid.StartsWith("timeout", StringComparison.Ordinal)
            ? db.Database.ExecuteSqlInterpolatedAsync($"UPDATE model_entries SET timeout_seconds = {row.TimeoutSeconds} WHERE id = {row.Id}")
            : db.Database.ExecuteSqlInterpolatedAsync($"UPDATE model_entries SET request_settings = CAST({row.RequestSettings} AS jsonb) WHERE id = {row.Id}"));
        Assert.Equal("23514", postgres.SqlState);
        var field = invalid.StartsWith("priority", StringComparison.Ordinal) ? "priority" : invalid.StartsWith("timeout", StringComparison.Ordinal) ? "timeout_seconds" : "request_settings";
        Assert.Equal("model_entries_" + field + "_check", postgres.ConstraintName);
        await transaction.RollbackAsync();
      }
  }
  [DatabaseFact]
  public async Task AdminModelsCursorPreservesExistingOrder()
  {
    await using (var owner = Database(true)) await owner.Database.MigrateAsync();
    using var host = new Host(true); using var admin = host.Client();
    await using var db = Database();
    var expected = await db.Models.Where(x => x.DeletedAt == null).OrderBy(x => x.Purpose).ThenBy(x => x.Tier).ThenBy(x => x.Role).ThenBy(x => x.Id).Select(x => x.Id.ToString()).Take(12).ToListAsync();
    var seen = new List<string>(); var after = "";
    while (seen.Count < expected.Count)
    {
      var page = (await admin.GetFromJsonAsync<JsonArray>("/api/admin/models?limit=2" + (after.Length > 0 ? "&after=" + after : "")))!;
      Assert.NotEmpty(page);
      seen.AddRange(page.Select(x => x!["model_entry_id"]!.GetValue<string>()));
      after = seen.Last();
    }
    Assert.Equal(expected, seen.Take(expected.Count));
    Assert.Equal(HttpStatusCode.BadRequest, (await admin.GetAsync("/api/admin/models?after=bad")).StatusCode);
  }
  [DatabaseFact]
  public async Task ActiveGrantsFilteredPagedAndValidated()
  {
    await using (var owner = Database(true)) await owner.Database.MigrateAsync();
    using var host = new Host(true); using var admin = host.Client();
    var right = "chat.tier." + RandomNumberGenerator.GetInt32(10000, 10000000);
    await using var db = Database(); db.Rights.Add(new Right { Key = right, Source = "tier" }); await db.SaveChangesAsync();
    var first = await admin.PostAsJsonAsync("/api/admin/grants", new { right_key = right, subject_type = "everyone" });
    var removed = (await first.Content.ReadFromJsonAsync<JsonObject>())!["id"]!.GetValue<string>();
    await admin.DeleteAsync("/api/admin/grants/" + removed);
    for (var n = 0; n < 3; n++) await admin.PostAsJsonAsync("/api/admin/grants", new { right_key = right, subject_type = "user", subject_id = "synthetic-" + Guid.NewGuid() });
    var page = (await admin.GetFromJsonAsync<JsonArray>($"/api/admin/grants?right_key={right}&limit=2"))!;
    Assert.Equal(2, page.Count);
    var after = page.Last()!["id"]!.GetValue<string>();
    var next = (await admin.GetFromJsonAsync<JsonArray>($"/api/admin/grants?right_key={right}&limit=2&after={after}"))!;
    Assert.Single(next); Assert.DoesNotContain(removed, page.ToJsonString() + next.ToJsonString());
    Assert.Equal(HttpStatusCode.BadRequest, (await admin.GetAsync("/api/admin/grants?after=bad")).StatusCode);
    Assert.Equal(HttpStatusCode.BadRequest, (await admin.GetAsync("/api/admin/grants?limit=201")).StatusCode);
  }
}
