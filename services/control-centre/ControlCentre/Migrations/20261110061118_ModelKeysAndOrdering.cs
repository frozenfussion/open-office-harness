// SPDX-License-Identifier: AGPL-3.0-only
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace ControlCentre.Migrations
{
  /// <inheritdoc />
  public partial class ModelKeysAndOrdering : Migration
  {
    /// <inheritdoc />
    protected override void Up(MigrationBuilder migrationBuilder)
    {
      migrationBuilder.DropIndex(
          name: "IX_model_entries_purpose_tier_role",
          table: "model_entries");

      migrationBuilder.AddColumn<string>(
          name: "api_key_encrypted",
          table: "model_entries",
          type: "text",
          nullable: true);

      migrationBuilder.AddColumn<decimal>(
          name: "input_price_per_million",
          table: "model_entries",
          type: "numeric(14,6)",
          precision: 14,
          scale: 6,
          nullable: false,
          defaultValue: 0m);

      migrationBuilder.AddColumn<decimal>(
          name: "output_price_per_million",
          table: "model_entries",
          type: "numeric(14,6)",
          precision: 14,
          scale: 6,
          nullable: false,
          defaultValue: 0m);

      migrationBuilder.AddColumn<int>(
          name: "priority",
          table: "model_entries",
          type: "integer",
          nullable: false,
          defaultValue: 100);

      migrationBuilder.AddColumn<string>(
          name: "request_settings",
          table: "model_entries",
          type: "jsonb",
          nullable: false,
          defaultValue: "{}");

      migrationBuilder.AddColumn<int>(
          name: "timeout_seconds",
          table: "model_entries",
          type: "integer",
          nullable: false,
          defaultValue: 120);

      migrationBuilder.AddColumn<string>(
          name: "title",
          table: "model_entries",
          type: "text",
          nullable: false,
          defaultValue: "");
    }

    /// <inheritdoc />
    protected override void Down(MigrationBuilder migrationBuilder) => throw new NotSupportedException("Migrations cannot delete data; add a forward migration");
  }
}
