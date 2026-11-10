// SPDX-License-Identifier: AGPL-3.0-only
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace ControlCentre.Migrations
{
  /// <inheritdoc />
  public partial class EnforceModelSettings : Migration
  {
    /// <inheritdoc />
    protected override void Up(MigrationBuilder migrationBuilder)
    {
      migrationBuilder.AddCheckConstraint(
          name: "model_entries_priority_check",
          table: "model_entries",
          sql: "priority BETWEEN 1 AND 1000");

      migrationBuilder.AddCheckConstraint(
          name: "model_entries_request_settings_check",
          table: "model_entries",
          sql: "jsonb_typeof(request_settings) = 'object'");

      migrationBuilder.AddCheckConstraint(
          name: "model_entries_timeout_seconds_check",
          table: "model_entries",
          sql: "timeout_seconds BETWEEN 10 AND 900");
    }

    /// <inheritdoc />
    protected override void Down(MigrationBuilder migrationBuilder) => throw new NotSupportedException("Migrations cannot delete data; add a forward migration");
  }
}
