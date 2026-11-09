// SPDX-License-Identifier: AGPL-3.0-only
using Microsoft.EntityFrameworkCore.Migrations;

namespace ControlCentre.Migrations.Scaffold;

// The initial SQL migration creates the schema. This migration establishes EF's generated model baseline.
public partial class SnapshotScaffold : Migration
{
  protected override void Up(MigrationBuilder migrationBuilder) { }
  protected override void Down(MigrationBuilder migrationBuilder) => throw new NotSupportedException("Migrations cannot delete data; add a forward migration");
}
