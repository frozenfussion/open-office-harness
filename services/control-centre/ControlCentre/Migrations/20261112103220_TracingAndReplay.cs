// SPDX-License-Identifier: AGPL-3.0-only
using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace ControlCentre.Migrations
{
  /// <inheritdoc />
  public partial class TracingAndReplay : Migration
  {
    /// <inheritdoc />
    protected override void Up(MigrationBuilder migrationBuilder)
    {
      migrationBuilder.AddColumn<string>(
          name: "traceparent",
          table: "outbox",
          type: "text",
          nullable: true);

      migrationBuilder.AddColumn<string>(
          name: "tracestate",
          table: "outbox",
          type: "text",
          nullable: true);

      migrationBuilder.CreateTable(
          name: "dead_letter_replays",
          columns: table => new
          {
            id = table.Column<Guid>(type: "uuid", nullable: false),
            dead_letter_id = table.Column<Guid>(type: "uuid", nullable: false),
            replayed_by = table.Column<string>(type: "text", nullable: false),
            replayed_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
            target_topic = table.Column<string>(type: "text", nullable: false),
            outcome = table.Column<string>(type: "text", nullable: false),
            error_code = table.Column<string>(type: "text", nullable: true)
          },
          constraints: table =>
          {
            table.PrimaryKey("PK_dead_letter_replays", x => x.id);
            table.CheckConstraint("dead_letter_replays_outcome_check", "outcome IN ('sent','failed')");
            table.ForeignKey(
                      name: "FK_dead_letter_replays_dead_letters_dead_letter_id",
                      column: x => x.dead_letter_id,
                      principalTable: "dead_letters",
                      principalColumn: "id");
          });

      migrationBuilder.Sql("""
                CREATE TRIGGER replays_no_update BEFORE UPDATE ON dead_letter_replays FOR EACH STATEMENT EXECUTE FUNCTION refuse_audit_change();
                CREATE TRIGGER replays_no_removal BEFORE DELETE OR TRUNCATE ON dead_letter_replays FOR EACH STATEMENT EXECUTE FUNCTION refuse_audit_change();
                DO $$ DECLARE app_role text;
                BEGIN
                  IF current_database() NOT IN ('controlcentre','controlcentre_test') THEN RAISE EXCEPTION 'Unexpected database'; END IF;
                  app_role := current_database() || '_app';
                  EXECUTE format('GRANT SELECT, INSERT ON dead_letter_replays TO %I', app_role);
                END $$;
                """);
      migrationBuilder.CreateIndex(
          name: "IX_dead_letter_replays_dead_letter_id_replayed_at",
          table: "dead_letter_replays",
          columns: new[] { "dead_letter_id", "replayed_at" });
    }

    protected override void Down(MigrationBuilder migrationBuilder) => throw new NotSupportedException("Migrations cannot delete data; add a forward migration");
  }
}
