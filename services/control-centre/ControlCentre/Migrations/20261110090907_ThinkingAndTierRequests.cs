// SPDX-License-Identifier: AGPL-3.0-only
using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace ControlCentre.Migrations
{
  /// <inheritdoc />
  public partial class ThinkingAndTierRequests : Migration
  {
    /// <inheritdoc />
    protected override void Up(MigrationBuilder migrationBuilder)
    {
      migrationBuilder.AddColumn<string>(
          name: "request_settings_thinking_off",
          table: "model_entries",
          type: "jsonb",
          nullable: true);

      migrationBuilder.CreateTable(
          name: "tier_requests",
          columns: table => new
          {
            id = table.Column<Guid>(type: "uuid", nullable: false),
            user_id = table.Column<string>(type: "text", nullable: false),
            tier = table.Column<int>(type: "integer", nullable: false),
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
            table.PrimaryKey("PK_tier_requests", x => x.id);
            table.CheckConstraint("tier_requests_reason_check", "reason IS NULL OR length(reason) <= 300");
            table.CheckConstraint("tier_requests_status_check", "status IN ('pending','approved','rejected')");
            table.CheckConstraint("tier_requests_tier_check", "tier > 0");
          });

      migrationBuilder.AddCheckConstraint(
          name: "model_entries_thinking_off_check",
          table: "model_entries",
          sql: "request_settings_thinking_off IS NULL OR jsonb_typeof(request_settings_thinking_off) = 'object'");

      migrationBuilder.CreateIndex(
          name: "tier_requests_paging",
          table: "tier_requests",
          columns: new[] { "requested_at", "id" },
          descending: new bool[0]);

      migrationBuilder.CreateIndex(
          name: "tier_requests_pending",
          table: "tier_requests",
          columns: new[] { "user_id", "tier" },
          unique: true,
          filter: "deleted_at IS NULL AND status = 'pending'");
      migrationBuilder.Sql("""
                CREATE TRIGGER no_removal BEFORE DELETE OR TRUNCATE ON tier_requests FOR EACH STATEMENT EXECUTE FUNCTION refuse_removal();
                DO $$ DECLARE app_role text;
                BEGIN
                    IF current_database() NOT IN ('controlcentre','controlcentre_test') THEN RAISE EXCEPTION 'Unexpected database'; END IF;
                    app_role := current_database() || '_app';
                    EXECUTE format('GRANT SELECT, INSERT, UPDATE ON tier_requests TO %I', app_role);
                END $$;
                """);
    }

    protected override void Down(MigrationBuilder migrationBuilder) => throw new NotSupportedException("Migrations cannot delete data; add a forward migration");
  }
}
