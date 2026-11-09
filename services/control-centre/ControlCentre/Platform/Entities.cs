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
    b.Entity<Person>().ToTable("people").HasIndex(x => x.UserId).IsUnique();
    b.Entity<Right>().ToTable("rights").HasIndex(x => x.Key).IsUnique();
    b.Entity<Grant>().ToTable("grants");
    b.Entity<ModelEntry>().ToTable("model_entries");
    b.Entity<Skill>().ToTable("skills").HasIndex(x => x.Name).IsUnique();
    b.Entity<Approval>().ToTable("approvals").HasIndex(x => x.RequestEventId).IsUnique();
    b.Entity<Approval>().Property(x => x.Status).IsConcurrencyToken();
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
    b.Entity<ModelEntry>().HasIndex(x => new { x.Purpose, x.Tier, x.Role })
        .IsUnique().AreNullsDistinct(false).HasFilter("deleted_at IS NULL");
  }
}
