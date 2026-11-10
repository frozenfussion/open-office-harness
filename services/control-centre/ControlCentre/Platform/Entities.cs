// SPDX-License-Identifier: AGPL-3.0-only
using Microsoft.EntityFrameworkCore;

namespace ControlCentre.Platform;

public abstract class BusinessRow
{
  public Guid Id { get; set; } = Guid.NewGuid();
  public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;
  public DateTimeOffset UpdatedAt { get; set; } = DateTimeOffset.UtcNow;
  public DateTimeOffset? DeletedAt { get; set; }
  public string CreatedBy { get; set; } = "system";
  public string UpdatedBy { get; set; } = "system";
}
public sealed class Person : BusinessRow
{
  public string UserId { get; set; } = "";
  public string? Email { get; set; }
  public string? Name { get; set; }
  public DateTimeOffset FirstSeenAt { get; set; } = DateTimeOffset.UtcNow;
  public DateTimeOffset LastSeenAt { get; set; } = DateTimeOffset.UtcNow;
}
public sealed class Right : BusinessRow
{
  public string Key { get; set; } = "";
  public string Description { get; set; } = "";
  public string Source { get; set; } = "";
}
public sealed class Grant : BusinessRow
{
  public string RightKey { get; set; } = "";
  public string SubjectType { get; set; } = "";
  public string? SubjectId { get; set; }
}
public sealed class ModelEntry : BusinessRow
{
  public string Title { get; set; } = "";
  [System.Text.Json.Serialization.JsonIgnore]
  public string? ApiKeyEncrypted { get; set; }
  public decimal InputPricePerMillion { get; set; }
  public decimal OutputPricePerMillion { get; set; }
  public int TimeoutSeconds { get; set; } = 120;
  public int Priority { get; set; } = 100;
  public string RequestSettings { get; set; } = "{}";
  public string Purpose { get; set; } = "";
  public int? Tier { get; set; }
  public string Role { get; set; } = "";
  public string Location { get; set; } = "";
  public string ApiType { get; set; } = "";
  public string EndpointUrl { get; set; } = "";
  public string ModelId { get; set; } = "";
  public string SecretRef { get; set; } = "";
  public int RateLimitPerMinute { get; set; }
  public decimal DailyBudget { get; set; }
  public string Health { get; set; } = "unknown";
}
public sealed class Skill : BusinessRow
{
  public string Name { get; set; } = "";
  public string Version { get; set; } = "";
  public string Manifest { get; set; } = "{}";
}
public sealed class Approval : BusinessRow
{
  public Guid RequestEventId { get; set; }
  public Guid CorrelationId { get; set; }
  public string RequesterUserId { get; set; } = "";
  public string Producer { get; set; } = "";
  public string Action { get; set; } = "";
  public string Details { get; set; } = "{}";
  public string Risk { get; set; } = "";
  public string RequestedBy { get; set; } = "";
  public string Status { get; set; } = "pending";
  public string? DecidedBy { get; set; }
  public string? Note { get; set; }
  public DateTimeOffset? DecidedAt { get; set; }
}
public sealed class ProcessedEvent
{
  public Guid EventId { get; set; }
  public string Topic { get; set; } = "";
  public DateTimeOffset ProcessedAt { get; set; } = DateTimeOffset.UtcNow;
}
public sealed class Outbox
{
  public Guid Id { get; set; } = Guid.NewGuid();
  public string Topic { get; set; } = "";
  public string Key { get; set; } = "";
  public string Envelope { get; set; } = "{}";
  public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;
  public DateTimeOffset? SentAt { get; set; }
}
public sealed class AuditRow
{
  public long Id { get; set; }
  public DateTimeOffset OccurredAt { get; set; } = DateTimeOffset.UtcNow;
  public string Actor { get; set; } = "";
  public string Action { get; set; } = "";
  public string Target { get; set; } = "";
  public string Outcome { get; set; } = "success";
  public string Detail { get; set; } = "{}";
  public Guid CorrelationId { get; set; }
}

public sealed class CentreDb(DbContextOptions<CentreDb> options) : DbContext(options)
{
  public DbSet<Person> People => Set<Person>();
  public DbSet<Right> Rights => Set<Right>();
  public DbSet<Grant> Grants => Set<Grant>();
  public DbSet<ModelEntry> Models => Set<ModelEntry>();
  public DbSet<Skill> Skills => Set<Skill>();
  public DbSet<Approval> Approvals => Set<Approval>();
  public DbSet<ProcessedEvent> ProcessedEvents => Set<ProcessedEvent>();
  public DbSet<Outbox> Outbox => Set<Outbox>();
  public DbSet<AuditRow> Audit => Set<AuditRow>();

  protected override void OnModelCreating(ModelBuilder b)
  {
    b.Entity<Person>().ToTable("people").HasAlternateKey(x => x.UserId);
    b.Entity<Right>().ToTable("rights").HasAlternateKey(x => x.Key);
    b.Entity<Grant>().ToTable("grants");
    b.Entity<ModelEntry>().ToTable("model_entries");
    b.Entity<Skill>().ToTable("skills").HasAlternateKey(x => x.Name);
    b.Entity<Approval>().ToTable("approvals").HasAlternateKey(x => x.RequestEventId);
    b.Entity<Approval>().Property(x => x.Status).IsConcurrencyToken();
    b.Entity<Grant>().HasOne<Right>().WithMany().HasForeignKey(x => x.RightKey).HasPrincipalKey(x => x.Key).OnDelete(DeleteBehavior.NoAction);
    b.Entity<Approval>().HasIndex(x => new { x.CreatedAt, x.Id }).IsDescending().HasDatabaseName("approvals_paging");
    b.Entity<Outbox>().HasIndex(x => new { x.CreatedAt, x.Id }).HasFilter("sent_at IS NULL").HasDatabaseName("outbox_pending");
    b.Entity<Right>().ToTable(t => t.HasCheckConstraint("rights_source_check", "source IN ('tier','skill','builtin')"));
    b.Entity<Grant>().ToTable(t =>
    {
      t.HasCheckConstraint("grants_subject_type_check", "subject_type IN ('user','everyone')");
      t.HasCheckConstraint("grants_check", "(subject_type = 'user' AND subject_id IS NOT NULL AND length(subject_id) > 0) OR (subject_type = 'everyone' AND subject_id IS NULL)");
    });
    b.Entity<ModelEntry>().ToTable(t =>
    {
      t.HasCheckConstraint("model_entries_priority_check", "priority BETWEEN 1 AND 1000");
      t.HasCheckConstraint("model_entries_timeout_seconds_check", "timeout_seconds BETWEEN 10 AND 900");
      t.HasCheckConstraint("model_entries_request_settings_check", "jsonb_typeof(request_settings) = 'object'");
      t.HasCheckConstraint("model_entries_role_check", "role IN ('main','backup')");
      t.HasCheckConstraint("model_entries_location_check", "location IN ('on_prem','cloud')");
      t.HasCheckConstraint("model_entries_rate_limit_per_minute_check", "rate_limit_per_minute > 0");
      t.HasCheckConstraint("model_entries_daily_budget_check", "daily_budget >= 0");
      t.HasCheckConstraint("model_entries_check", "(purpose = 'chat' AND tier IS NOT NULL AND tier > 0) OR (purpose <> 'chat' AND tier IS NULL)");
    });
    b.Entity<Approval>().ToTable(t => t.HasCheckConstraint("approvals_status_check", "status IN ('pending','approved','rejected')"));
    b.Entity<ProcessedEvent>().ToTable("processed_events").HasKey(x => x.EventId);
    b.Entity<Outbox>().ToTable("outbox");
    b.Entity<AuditRow>().ToTable("audit_log");
    b.Entity<Skill>().Property(x => x.Manifest).HasColumnType("jsonb");
    b.Entity<Approval>().Property(x => x.Details).HasColumnType("jsonb");
    b.Entity<Outbox>().Property(x => x.Envelope).HasColumnType("jsonb");
    b.Entity<AuditRow>().Property(x => x.Detail).HasColumnType("jsonb");
    foreach (var entity in b.Model.GetEntityTypes())
      foreach (var property in entity.GetProperties())
        property.SetColumnName(System.Text.Json.JsonNamingPolicy.SnakeCaseLower.ConvertName(property.Name));
    b.Entity<Grant>().HasIndex(x => new { x.RightKey, x.SubjectType, x.SubjectId })
        .IsUnique().AreNullsDistinct(false).HasFilter("deleted_at IS NULL");
    b.Entity<ModelEntry>().Property(x => x.RequestSettings).HasColumnType("jsonb").HasDefaultValue("{}");
    b.Entity<ModelEntry>().Property(x => x.Title).HasDefaultValue("");
    b.Entity<ModelEntry>().Property(x => x.Priority).HasDefaultValue(100);
    b.Entity<ModelEntry>().Property(x => x.TimeoutSeconds).HasDefaultValue(120);
    b.Entity<ModelEntry>().Property(x => x.InputPricePerMillion).HasPrecision(14, 6).HasDefaultValue(0m);
    b.Entity<ModelEntry>().Property(x => x.OutputPricePerMillion).HasPrecision(14, 6).HasDefaultValue(0m);
  }
}
