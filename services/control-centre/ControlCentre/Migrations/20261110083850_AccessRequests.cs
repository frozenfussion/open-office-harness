// SPDX-License-Identifier: AGPL-3.0-only
using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace ControlCentre.Migrations
{
  /// <inheritdoc />
  public partial class AccessRequests : Migration
  {
    /// <inheritdoc />
    protected override void Up(MigrationBuilder migrationBuilder)
    {
      migrationBuilder.CreateTable(
          name: "access_requests",
          columns: table => new
          {
            id = table.Column<Guid>(type: "uuid", nullable: false),
            user_id = table.Column<string>(type: "text", nullable: false),
            name = table.Column<string>(type: "text", nullable: true),
            email = table.Column<string>(type: "text", nullable: true),
            organisation = table.Column<string>(type: "text", nullable: true),
            reason = table.Column<string>(type: "text", nullable: true),
            status = table.Column<string>(type: "text", nullable: false),
            requested_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
            decided_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
            decided_by = table.Column<string>(type: "text", nullable: true),
            approved_tier = table.Column<int>(type: "integer", nullable: true),
            created_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
            updated_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
            deleted_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
            created_by = table.Column<string>(type: "text", nullable: false),
            updated_by = table.Column<string>(type: "text", nullable: false)
          },
          constraints: table =>
          {
            table.PrimaryKey("PK_access_requests", x => x.id);
            table.UniqueConstraint("AK_access_requests_user_id", x => x.user_id);
            table.CheckConstraint("access_requests_status_check", "status IN ('pending','approved','rejected')");
          });

      migrationBuilder.CreateIndex(
          name: "access_requests_paging",
          table: "access_requests",
          columns: new[] { "requested_at", "id" },
          descending: new bool[0]);
      migrationBuilder.Sql("""
                CREATE TRIGGER no_removal BEFORE DELETE OR TRUNCATE ON access_requests FOR EACH STATEMENT EXECUTE FUNCTION refuse_removal();
                DO $$ DECLARE app_role text;
                BEGIN
                    IF current_database() NOT IN ('controlcentre','controlcentre_test') THEN RAISE EXCEPTION 'Unexpected database'; END IF;
                    app_role := current_database() || '_app';
                    EXECUTE format('GRANT SELECT, INSERT, UPDATE ON access_requests TO %I', app_role);
                END $$;
                """);
      migrationBuilder.Sql("LOCK TABLE people, grants IN SHARE MODE");
      migrationBuilder.Sql(BackfillSql);
    }

    protected override void Down(MigrationBuilder migrationBuilder) => throw new NotSupportedException("Migrations cannot delete data; add a forward migration");

    public const string BackfillSql = """
            WITH eligible AS (
                SELECT user_id FROM people WHERE first_seen_at < transaction_timestamp()
                UNION
                SELECT subject_id FROM grants WHERE subject_type = 'user' AND deleted_at IS NULL AND created_at < transaction_timestamp()
            ), inserted AS (
                INSERT INTO access_requests (id, user_id, name, email, organisation, reason, status, requested_at,
                    decided_at, decided_by, approved_tier, created_at, updated_at, deleted_at, created_by, updated_by)
                SELECT gen_random_uuid(), e.user_id, left(trim(p.name),200), left(trim(p.email),320), NULL, NULL, 'approved', transaction_timestamp(),
                    transaction_timestamp(), 'migration', NULL, transaction_timestamp(), transaction_timestamp(), NULL, 'migration', 'migration'
                FROM eligible e LEFT JOIN people p ON p.user_id=e.user_id
                ON CONFLICT (user_id) DO NOTHING
                RETURNING user_id
            ), audited AS (
                INSERT INTO audit_log (occurred_at, actor, action, target, outcome, detail, correlation_id)
                SELECT transaction_timestamp(), 'migration', 'access.approved', user_id, 'success',
                    jsonb_build_object('user_id',user_id,'status','approved','decided_by','migration','approved_tier',NULL), gen_random_uuid()
                FROM inserted RETURNING occurred_at, actor, action, target, outcome, correlation_id
            )
            INSERT INTO outbox (id, topic, key, envelope, created_at)
            SELECT gen_random_uuid(), 'audit.events', correlation_id::text,
                jsonb_build_object('event_id',gen_random_uuid(),'type','audit.event','version',1,
                    'occurred_at',to_char(occurred_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
                    'correlation_id',correlation_id,'user_id',target,'producer','control-centre',
                    'payload',jsonb_build_object('actor',actor,'action',action,'target',target,'outcome',outcome)), transaction_timestamp()
            FROM audited;
            """;
  }
}
