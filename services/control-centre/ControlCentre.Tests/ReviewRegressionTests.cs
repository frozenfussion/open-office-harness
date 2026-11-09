// SPDX-License-Identifier: AGPL-3.0-only
using System.Data.Common;
using System.Net;
using System.Net.Http.Json;
using System.Text.Json.Nodes;
using ControlCentre.Platform;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;
using Microsoft.Extensions.Logging;
using Xunit;
using static ControlCentre.Tests.RoutesWithoutDatabaseTests;

namespace ControlCentre.Tests;

public sealed class ReviewRegressionTests
{
  private static CentreDb Database(bool owner = false, params IInterceptor[] interceptors) => new(
    new DbContextOptionsBuilder<CentreDb>().UseNpgsql(DatabaseConnections.Configure(TestSettings.Load()[owner ? "CC_TEST_DB_MIGRATE_CONNECTION" : "CC_TEST_DB_CONNECTION"]))
      .AddInterceptors(interceptors).Options);
  private static async Task Migrate()
  {
    await using var db = Database(true); await db.Database.MigrateAsync();
  }
  [DatabaseFact]
  public async Task PersonCreationRacesDoNotConflictAndUnchangedReadsDoNotAudit()
  {
    await Migrate();
    var user = "test-person-" + Guid.NewGuid().ToString("N");
    using var host = new Host(true);
    using var first = host.Client("self", user); using var second = host.Client("self", user);
    var responses = await Task.WhenAll(first.GetAsync("/api/rights/me?user_id=" + user), second.GetAsync("/api/rights/me?user_id=" + user));
    Assert.All(responses, response => Assert.Equal(HttpStatusCode.OK, response.StatusCode));
    await using var db = Database();
    Assert.Single(await db.People.Where(x => x.UserId == user).ToListAsync());
    var audits = await db.Audit.Where(x => x.Target == user).ToListAsync();
    var created = Assert.Single(audits);
    Assert.Equal("person.created", created.Action);
    var person = await db.People.AsNoTracking().SingleAsync(x => x.UserId == user);
    for (var i = 0; i < 3; i++) Assert.Equal(HttpStatusCode.OK, (await first.GetAsync("/api/rights/me?user_id=" + user)).StatusCode);
    var unchanged = await db.People.AsNoTracking().SingleAsync(x => x.UserId == user);
    Assert.Equal(person.UpdatedAt, unchanged.UpdatedAt);
    Assert.Equal(person.LastSeenAt, unchanged.LastSeenAt);
    Assert.Single(await db.Audit.Where(x => x.Target == user).ToListAsync());
    await db.People.Where(x => x.UserId == user).ExecuteUpdateAsync(set => set.SetProperty(x => x.LastSeenAt, DateTimeOffset.UtcNow.AddHours(-2)));
    Assert.Equal(HttpStatusCode.OK, (await first.GetAsync("/api/rights/me?user_id=" + user)).StatusCode);
    var refreshed = await db.People.AsNoTracking().SingleAsync(x => x.UserId == user);
    Assert.True(refreshed.LastSeenAt > person.LastSeenAt);
    Assert.Equal(person.UpdatedAt, refreshed.UpdatedAt);
    Assert.Single(await db.Audit.Where(x => x.Target == user).ToListAsync());
    using var changed = host.Client("self", user, email: "updated@test.invalid", name: "Updated Synthetic User");
    Assert.Equal(HttpStatusCode.OK, (await changed.GetAsync("/api/rights/me?user_id=" + user)).StatusCode);
    var updated = await db.People.AsNoTracking().SingleAsync(x => x.UserId == user);
    Assert.Equal("updated@test.invalid", updated.Email);
    Assert.Equal("Updated Synthetic User", updated.Name);
    Assert.Equal(refreshed.LastSeenAt, updated.LastSeenAt);
    audits = await db.Audit.Where(x => x.Target == user).ToListAsync();
    Assert.Equal(2, audits.Count);
    Assert.Single(audits, x => x.Action == "person.updated");
    foreach (var audit in audits) Assert.True(await db.Outbox.AnyAsync(x => x.Key == audit.CorrelationId.ToString()));
  }
  [DatabaseFact]
  public async Task PeopleAndRightsCanPageAndModelsHaveStableMeaningfulOrder()
  {
    await Migrate(); await using var db = Database();
    var prefix = "test-paging-" + Guid.NewGuid().ToString("N") + "-";
    foreach (var suffix in new[] { "a", "b", "c" })
    {
      db.People.Add(new Person { UserId = prefix + suffix });
      db.Rights.Add(new Right { Key = prefix + suffix, Description = "Synthetic right", Source = "builtin" });
      db.Models.Add(new ModelEntry { Purpose = prefix + suffix, Role = "backup", Location = "cloud", ApiType = "test", EndpointUrl = "https://test.invalid", ModelId = "test", SecretRef = "test-none", RateLimitPerMinute = 1 });
    }
    await db.SaveChangesAsync();
    using var host = new Host(true); using var client = host.Client();
    foreach (var (route, field) in new[] { ("people", "user_id"), ("rights", "key") })
    {
      var a = (await client.GetFromJsonAsync<JsonArray>($"/api/admin/{route}?limit=1&after={prefix}"))!;
      Assert.Single(a); Assert.Equal(prefix + "a", a[0]![field]!.ToString());
      var b = (await client.GetFromJsonAsync<JsonArray>($"/api/admin/{route}?limit=1&after={prefix}a"))!;
      Assert.Single(b); Assert.Equal(prefix + "b", b[0]![field]!.ToString());
      Assert.Equal(HttpStatusCode.BadRequest, (await client.GetAsync($"/api/admin/{route}?after=")).StatusCode);
    }
    var expected = await db.Models.Where(x => x.DeletedAt == null).OrderBy(x => x.Purpose).ThenBy(x => x.Tier).ThenBy(x => x.Role).ThenBy(x => x.Id).Take(200).Select(x => x.Id.ToString()).ToListAsync();
    var models = (await client.GetFromJsonAsync<JsonArray>("/api/admin/models?limit=200"))!;
    Assert.Equal(expected, models.Select(x => x!["model_entry_id"]!.GetValue<string>()));
    Assert.Equal(HttpStatusCode.BadRequest, (await client.GetAsync("/api/admin/models?limit=201")).StatusCode);
  }
  [DatabaseFact]
  public async Task TransientConsumerFailuresRetryAndOnlyExhaustionGoesToDlq()
  {
    await Migrate();
    foreach (var failures in new[] { 1, 3 })
    {
      var fault = new InsertFailure(failures);
      await using var db = Database(false, fault);
      var delay = new FakeDelay(); var consumer = new ApprovalConsumer(db, new SchemaChecks(), delay);
      var envelope = Envelope(); var correlation = envelope["correlation_id"]!.GetValue<string>();
      await consumer.Handle(new KafkaRecord("approvals.requested", envelope.ToJsonString(), new object()), default);
      Assert.Equal(failures == 1 ? new[] { 1d } : new[] { 1d, 5d, 15d }, delay.Waits.Select(x => x.TotalSeconds));
      Assert.Equal(failures == 1, await db.Approvals.AnyAsync(x => x.CorrelationId.ToString() == correlation));
      Assert.Equal(failures == 3, await db.Outbox.AnyAsync(x => x.Key == correlation && x.Topic == "dlq.approvals.requested"));
      await consumer.Handle(new KafkaRecord("approvals.requested", envelope.ToJsonString(), new object()), default);
      Assert.Equal(failures, fault.Failed);
    }
  }
  [DatabaseFact]
  public async Task LiveConstraintAndIndexNamesMatchEfMetadata()
  {
    await Migrate(); await using var db = Database();
    foreach (var entity in db.Model.GetEntityTypes())
    {
      var table = entity.GetTableName()!;
      var constraints = await db.Database.SqlQuery<string>($"SELECT c.conname AS \"Value\" FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname='public' AND t.relname={table}").ToListAsync();
      foreach (var key in entity.GetKeys()) Assert.Contains(key.GetName(), constraints);
      foreach (var foreign in entity.GetForeignKeys()) Assert.Contains(foreign.GetConstraintName(), constraints);
      var indexes = await db.Database.SqlQuery<string>($"SELECT indexname AS \"Value\" FROM pg_indexes WHERE schemaname='public' AND tablename={table}").ToListAsync();
      foreach (var index in entity.GetIndexes()) Assert.Contains(index.GetDatabaseName(), indexes);
    }
  }
  [Fact]
  public void FailureDiagnosticsRetainTypeAndReasonWithoutSensitiveValues()
  {
    var logger = new CaptureLogger();
    Diagnostics.Failure(logger, "Synthetic operation", new InvalidOperationException("Synthetic failure for Synthetic User at user@test.invalid with 'private value'"), ["Synthetic User"]);
    Assert.Contains("System.InvalidOperationException", logger.Message);
    Assert.Contains("Synthetic failure", logger.Message);
    Assert.DoesNotContain("Synthetic User", logger.Message);
    Assert.DoesNotContain("user@test.invalid", logger.Message);
    Assert.DoesNotContain("private value", logger.Message);
  }
  private sealed class InsertFailure(int count) : DbCommandInterceptor
  {
    public int Failed { get; private set; }
    public override ValueTask<InterceptionResult<DbDataReader>> ReaderExecutingAsync(DbCommand command, CommandEventData eventData, InterceptionResult<DbDataReader> result, CancellationToken cancellationToken = default)
    {
      if (Failed < count && command.CommandText.Contains("INSERT INTO approvals", StringComparison.Ordinal))
      {
        Failed++;
        throw new IOException("Synthetic temporary database failure");
      }
      return base.ReaderExecutingAsync(command, eventData, result, cancellationToken);
    }
  }
  private sealed class CaptureLogger : ILogger
  {
    public string Message { get; private set; } = "";
    public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;
    public bool IsEnabled(LogLevel level) => true;
    public void Log<TState>(LogLevel level, EventId id, TState state, Exception? error, Func<TState, Exception?, string> formatter) => Message = formatter(state, error);
  }
}
