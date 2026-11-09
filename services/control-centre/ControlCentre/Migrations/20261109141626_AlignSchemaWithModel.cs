// SPDX-License-Identifier: AGPL-3.0-only
using Microsoft.EntityFrameworkCore.Migrations;

namespace ControlCentre.Migrations;

public partial class AlignSchemaWithModel : Migration
{
  protected override void Up(MigrationBuilder migrationBuilder)
  {
    // Renaming a PostgreSQL constraint's index also renames its constraint, preserving its data and references.
    foreach (var table in new[] { "people", "rights", "grants", "model_entries", "skills", "approvals", "processed_events", "outbox", "audit_log" })
      migrationBuilder.RenameIndex(name: table + "_pkey", table: table, newName: "PK_" + table);
    migrationBuilder.RenameIndex(name: "people_user_id_key", table: "people", newName: "AK_people_user_id");
    migrationBuilder.RenameIndex(name: "rights_key_key", table: "rights", newName: "AK_rights_key");
    migrationBuilder.RenameIndex(name: "skills_name_key", table: "skills", newName: "AK_skills_name");
    migrationBuilder.RenameIndex(name: "approvals_request_event_id_key", table: "approvals", newName: "AK_approvals_request_event_id");
    migrationBuilder.RenameIndex(name: "grants_active", table: "grants", newName: "IX_grants_right_key_subject_type_subject_id");
    migrationBuilder.RenameIndex(name: "models_active", table: "model_entries", newName: "IX_model_entries_purpose_tier_role");
    migrationBuilder.DropForeignKey(name: "grants_right_key_fkey", table: "grants");
    migrationBuilder.AddForeignKey(name: "FK_grants_rights_right_key", table: "grants", column: "right_key", principalTable: "rights", principalColumn: "key");
    // The checks and the two named indexes already exist; the generated model now records them.
  }
  protected override void Down(MigrationBuilder migrationBuilder) => throw new NotSupportedException("Migrations cannot delete data; add a forward migration");
}
