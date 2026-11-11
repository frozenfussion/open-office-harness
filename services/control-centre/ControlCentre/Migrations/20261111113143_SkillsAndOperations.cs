// SPDX-License-Identifier: AGPL-3.0-only
using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace ControlCentre.Migrations
{
  /// <inheritdoc />
  public partial class SkillsAndOperations : Migration
  {
    /// <inheritdoc />
    protected override void Up(MigrationBuilder migrationBuilder)
    {
      migrationBuilder.AddColumn<bool>(
          name: "is_service_account",
          table: "people",
          type: "boolean",
          nullable: false,
          defaultValue: false);

      migrationBuilder.AddColumn<DateTimeOffset>(
          name: "health_changed_at",
          table: "model_entries",
          type: "timestamp with time zone",
          nullable: true);

      migrationBuilder.AddColumn<string>(
          name: "health_reason",
          table: "model_entries",
          type: "text",
          nullable: true);

      migrationBuilder.AddColumn<bool>(
          name: "is_service_account",
          table: "access_requests",
          type: "boolean",
          nullable: false,
          defaultValue: false);

      migrationBuilder.CreateTable(
          name: "dead_letters",
          columns: table => new
          {
            id = table.Column<Guid>(type: "uuid", nullable: false),
            topic = table.Column<string>(type: "text", nullable: false),
            partition = table.Column<int>(type: "integer", nullable: false),
            offset = table.Column<long>(type: "bigint", nullable: false),
            received_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
            error_code = table.Column<string>(type: "text", nullable: false),
            error_message = table.Column<string>(type: "text", nullable: false),
            original_message = table.Column<string>(type: "text", nullable: false),
            correlation_id = table.Column<Guid>(type: "uuid", nullable: true)
          },
          constraints: table =>
          {
            table.PrimaryKey("PK_dead_letters", x => x.id);
          });

      migrationBuilder.CreateTable(
          name: "skill_requests",
          columns: table => new
          {
            id = table.Column<Guid>(type: "uuid", nullable: false),
            user_id = table.Column<string>(type: "text", nullable: false),
            skill = table.Column<string>(type: "text", nullable: false),
            reason = table.Column<string>(type: "text", nullable: true),
            status = table.Column<string>(type: "text", nullable: false),
            requested_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
            decided_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
            decided_by = table.Column<string>(type: "text", nullable: true),
            created_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
            updated_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
            deleted_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
            created_by = table.Column<string>(type: "text", nullable: false),
            updated_by = table.Column<string>(type: "text", nullable: false)
          },
          constraints: table =>
          {
            table.PrimaryKey("PK_skill_requests", x => x.id);
            table.CheckConstraint("skill_requests_reason_check", "reason IS NULL OR length(reason) <= 300");
            table.CheckConstraint("skill_requests_status_check", "status IN ('pending','approved','rejected')");
          });

      migrationBuilder.Sql("""
                CREATE TRIGGER no_removal BEFORE DELETE OR TRUNCATE ON skill_requests FOR EACH STATEMENT EXECUTE FUNCTION refuse_removal();
                CREATE TRIGGER no_removal BEFORE DELETE OR TRUNCATE ON dead_letters FOR EACH STATEMENT EXECUTE FUNCTION refuse_removal();
                CREATE TRIGGER dead_letters_immutable BEFORE UPDATE ON dead_letters FOR EACH ROW EXECUTE FUNCTION protect_system_row();
                DO $$ DECLARE app_role text;
                BEGIN
                  IF current_database() NOT IN ('controlcentre','controlcentre_test') THEN RAISE EXCEPTION 'Unexpected database'; END IF;
                  app_role := current_database() || '_app';
                  EXECUTE format('GRANT SELECT, INSERT, UPDATE ON skill_requests TO %I', app_role);
                  EXECUTE format('GRANT SELECT, INSERT ON dead_letters TO %I', app_role);
                END $$;
                """);

      migrationBuilder.AddCheckConstraint(
          name: "model_entries_health_check",
          table: "model_entries",
          sql: "health IN ('unknown','ok','down')");

      migrationBuilder.CreateIndex(
          name: "IX_dead_letters_received_at_id",
          table: "dead_letters",
          columns: new[] { "received_at", "id" },
          descending: new bool[0]);

      migrationBuilder.CreateIndex(
          name: "IX_dead_letters_topic_partition_offset",
          table: "dead_letters",
          columns: new[] { "topic", "partition", "offset" },
          unique: true);

      migrationBuilder.CreateIndex(
          name: "skill_requests_paging",
          table: "skill_requests",
          columns: new[] { "requested_at", "id" },
          descending: new bool[0]);

      migrationBuilder.CreateIndex(
          name: "skill_requests_pending",
          table: "skill_requests",
          columns: new[] { "user_id", "skill" },
          unique: true,
          filter: "deleted_at IS NULL AND status = 'pending'");
    }

    protected override void Down(MigrationBuilder migrationBuilder) => throw new NotSupportedException("Migrations cannot delete data; add a forward migration");
  }
}
