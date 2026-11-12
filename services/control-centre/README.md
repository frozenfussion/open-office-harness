# QUICK GUIDE

1. **Build the program.** Type this in your harness terminal, in the plain shell. No password is needed. Start in your worktree's `services/control-centre` folder. This builds with warnings treated as errors. Good result: `Build succeeded`, zero warnings and errors.

   ```bash
   cd "$(git rev-parse --show-toplevel)/services/control-centre"
   dotnet build -warnaserror
   dotnet build-server shutdown
   ```

2. **Run the tests.** Type this in your harness terminal, in the plain shell. No password is needed. Start in your worktree's `services/control-centre` folder. This runs the real HTTP routes in memory with signed test tokens and fake Kafka. Good result: all tests pass. If the database settings file is absent, only the database tests are skipped; Part A is ready only after those pass too.

   ```bash
   cd "$(git rev-parse --show-toplevel)/services/control-centre"
   dotnet test
   dotnet build-server shutdown
   ```

   Aziz makes the test database by following Part B's README step for `install/59-control-centre-databases.sh`. That writes `~/.config/ooh/control-centre-test.env` with mode 600. Tests read it without printing it, migrate as `controlcentre_test`, then run as `controlcentre_test_app`. Only the owner-trigger checks use the owner. Tests never use the live database and never erase data. Each uses unique records or rolls a transaction back.

3. **Check formatting.** Type this in your harness terminal, in the plain shell. No password is needed. Start in your worktree's `services/control-centre` folder. This checks C# formatting without changing files. Good result: no changes required and exit code zero.

   ```bash
   cd "$(git rev-parse --show-toplevel)/services/control-centre"
   dotnet format --verify-no-changes
   dotnet build-server shutdown
   ```

4. **Run the contract checks.** Type this in your harness terminal, in the plain shell. No password is needed. Start in your worktree's root folder. This checks the schemas and every HTTP example. Good result: all tests pass.

   ```bash
   cd "$(git rev-parse --show-toplevel)"
   uv run --project contracts/check pytest
   ```

5. **Apply migrations locally to the test database.** Type this in your harness terminal, in the plain shell. No password is needed. Start in your worktree's `services/control-centre` folder. This reads only the test settings and applies pending migrations, then exits. Good result: exit code zero. The database setup script from Part B must have finished first. Never paste connection strings into chat or use shell tracing (`set -x`).

   ```bash
   cd "$(git rev-parse --show-toplevel)/services/control-centre"
   (
     set -euo pipefail
     trap 'dotnet build-server shutdown' EXIT
     . "$HOME/.config/ooh/control-centre-test.env"
     export CC_DB_MIGRATE_CONNECTION="$CC_TEST_DB_MIGRATE_CONNECTION"
     dotnet run --project ControlCentre -- migrate
     dotnet build-server shutdown
   )
   ```

6. **Deploy, start, stop, restart, inspect logs, or recover after reboot.** Follow the repository's top-level README Quick Guide, maintained by Part C. The deployed service starts under Kubernetes; the builders do not start a server or change the cluster. The image takes `migrate` in its init container and serves port 8080 publicly and port 8081 internally in its main container. The Docker build context is `services/control-centre`.

7. **Read a trace or replay a failed message.** On your PC, open the Admin Console,
   sign in as an administrator, and choose **Audit → Trace** on a row. For recovery,
   choose **Failed messages**, select a row, fix the cause, then **Replay → Confirm replay**.
   A sent result confirms Kafka delivery; watch the job for completion. A failed
   result is retained in replay history. Traces can expire after a Jaeger restart;
   audit rows and replay history remain.

If `dotnet` is missing or reports a different SDK, finish the home-folder SDK installation in the stage spec first; this package requires SDK `10.0.403`. If package restore fails, check network access and retry the build. If a database test fails to connect, finish Part B's database setup and rerun the tests. If a database test rejects the database name or role, rerun the setup script; do not substitute live settings. If migrations fail, retain their error message without connection strings for review; never edit a migration already applied. The service reads environment variables only and reports a missing variable by name, without its value.

# Control Centre

One ASP.NET Core deployable with Rights, Registry, Approvals, Audit and Platform modules. Environment variable names and deployment values are fixed in the Stage 1 spec, section 8. The running program gets `CC_DB_CONNECTION`; only migration mode reads `CC_DB_MIGRATE_CONNECTION`. The owner connection is not needed by the running service. JWT verification checks the signature, issuer, audience, expiry and subject. Health is the only public route. Unknown body fields, duplicate fields, unknown query fields and repeated query fields are rejected. Lists added in Stage 1 accept `limit` 1–200, default 50. People and rights are sorted by `user_id` and `key`; pass the last value as `after` for the next page. Admin models sort by `(purpose, tier, role, id)`; optional `after` is the last model entry UUID and continues that same order. The four existing contract routes retain their original input shapes.

Changes, audit rows and outgoing envelopes share one database transaction. Every HTTP request has one correlation UUID. People are created with a race-safe insert. Their email and name are written and audited only on create or change. The system timestamp `last_seen_at` is refreshed hourly and on local-day changes, without an audit row. Approval decisions retain the requester's identity and correlation in `approval.decided`. The local audit detail holds before/after data; published audit events contain only actor, action, target and outcome.

The initial migration creates the schema, constraints, seed right, database grants and protection triggers in SQL. `SnapshotScaffold` records EF's generated model baseline without changing tables. The new `AlignSchemaWithModel` migration brings object names and EF metadata into agreement, including keys, the grants foreign key, constraints and paging/outbox indexes. Earlier applied migrations are retained unchanged. All later schema changes must be new migrations. The audit table is append-only, every table refuses hard deletion and truncation, processed-event rows are immutable, and an outbox row can only have `sent_at` set once. The application role cannot update audit rows or remove their trigger. Tests proving triggers use transactions that roll back even if an assertion fails.

The Kafka consumer validates the bundled contract schemas, ignores processed event ids, and sends invalid envelopes straight to the DLQ through the outbox. Transient processing failures get three attempts with 1, 5 and 15 second waits before the DLQ. Offsets are committed only after the durable database work succeeds. Kafka sends time out after 10 seconds and the outbox retries on its next pass. Outbox publishing locks pending rows across replicas and marks them sent after broker acknowledgement. A crash between broker acknowledgement and the database commit can produce a duplicate, as permitted by the event contract; consumers must deduplicate by event id.

`ControlCentre/Platform/Schemas` contains exact copies of the Stage 0 event and manifest schemas for offline validation inside the image. The schema-copy check in the test suite verifies they match the contracts. Tests use runtime-generated signing keys, fake Kafka and no real identity provider or AI calls. Test data is synthetic.

Dependencies and SDK versions are pinned in the project files, lock files, local tool manifest and `global.json`. The latter selects Microsoft's testing platform for the pinned xUnit version on .NET 10. JSON logs include sanitized exception types and messages, with authentication diagnostics at Information. Request bodies, tokens, database statements and personal details are excluded. Migrations run in the foreground and exit. The pinned chiseled image runs as its built-in non-root application user; runtime configuration comes from environment variables, and no writable application files are needed. `DOTNET_EnableDiagnostics=0` disables the runtime diagnostics socket, and data protection uses ephemeral in-memory keys. The read-only-root check runs the in-memory HTTP health test under `bwrap` with `/` (including `/tmp`) mounted read-only; it checks application startup without starting a separate server. This host check does not prove the chiseled image's native Kafka library; that remains a live image check.

The local tool manifest `.config/dotnet-tools.json` is an SPDX-header exception: the .NET tool parser rejects JSON comments. `global.json` accepts its SPDX comment. Generated package lock files and contract data examples retain their required JSON formats.

Container binding comes from `ASPNETCORE_HTTP_PORTS="8080;8081"` in the run image. The environment-only configuration restores the `ASPNETCORE_` provider, so Kestrel binds all interfaces on that port; `ASPNETCORE_URLS` can override it through normal ASP.NET Core configuration. Application, migration and EF tooling connections explicitly disable Npgsql GSS encryption because the chiseled image has no Kerberos library. The image and password authentication stay unchanged.


# Stage 2 keys and internal registry

Run `install/63-control-centre-keys.sh` before deploying the new image with `61`.
The complete deployment and everyday commands are in
[the Admin Console Quick Guide](../../apps/admin-console/README.md).
The application requires `CC_KEY_ENCRYPTION_KEY` to be 32 bytes encoded as base64;
startup refuses missing or invalid values without printing them. Migration mode
does not need this key. AES-256-GCM stores `v1:<nonce>:<ciphertext>:<tag>`;
nonce, ciphertext and tag are base64. The model entry UUID is authenticated as
associated data. Replacing an endpoint or connection type clears its key unless
a replacement key is included. Admin views and before/after audit details expose
only `has_key`; audit key changes say `set`, `changed` or `removed`. Deletion audit
records also use the safe model view. Key reads log only the model entry ID,
return `Cache-Control: no-store`, and do not create audit rows.

Only the Gateway service account may use `GET /api/models` and
`GET /api/models/{id}/key`, and only through port 8081. Both return JSON 404 on
8080 before authentication. There is no Ingress for 8081. The internal registry
includes UTC `created_at`, priority and the new request settings and prices.
The new migration drops the existing unique model index (renamed by Stage 1 to
`IX_model_entries_purpose_tier_role`); any number of entries can share a purpose,
tier and role. No previously applied migration is edited. Down migrations are
refused to preserve data.

`GET /api/admin/grants` lists active grants with optional `right_key`, `limit`
(1–200) and `after` (last UUID); rows are ordered by UUID. Leaving out the right
filter lets the console discover tiers with grants even when no model remains.
The Stage 1 live check now reserves tier 99 for both its model and rights checks.
Its internal registry check uses a trapped port-forward on local port 18081;
a busy port is a `STOP:` with a recovery instruction. Builders do not run that
script because it changes the cluster. Claude runs it in the shell tile.

**Check migration metadata.** Type this in your harness terminal, in the plain
shell. No password is needed. This restores the pinned EF tool, loads the test
settings privately and checks the model snapshot. Good result: no pending model
changes. This command does not apply a migration or change the cluster.

```bash
cd ~/projects/worktrees/stage-4-part-d/services/control-centre
(
  set -euo pipefail
  trap 'dotnet build-server shutdown' EXIT
  dotnet tool restore
  . "$HOME/.config/ooh/control-centre-test.env"
  export CC_DB_MIGRATE_CONNECTION="$CC_TEST_DB_MIGRATE_CONNECTION"
  dotnet ef migrations has-pending-model-changes --project ControlCentre
  dotnet build-server shutdown
)
```

**Optional encryption Secret backup.** Type this in your harness terminal, in
the plain shell. No password is needed; the folder does not matter. This saves
the Secret in a private file under your home configuration folder, never in
the repo. Good result: a mode-600 backup file; do not display its contents.
Skip this step if you do not want a backup.

```bash
(
  set -euo pipefail
  umask 077
  mkdir -p "$HOME/.config/ooh"
  kubectl -n ooh-apps get secret control-centre-keys -o json > "$HOME/.config/ooh/control-centre-keys.backup.json"
  chmod 600 "$HOME/.config/ooh/control-centre-keys.backup.json"
)
```

Keep that backup in a private place. If the Secret is lost and there is no
backup, create a replacement with 63, restart the Control Centre through its
deploy script and retype all saved provider keys in the Admin Console.
63 always retains an existing Secret; it never rotates or overwrites it.
A wrong encryption key returns a generic key-unavailable error without the key
or ciphertext. The app cannot recognize a wrong-but-valid 32-byte key at startup;
it detects authentication failure when a saved provider key is read.

Builder check sessions end with `dotnet build-server shutdown` so automatic MSBuild and compiler daemons do not remain running.

The follow-up `EnforceModelSettings` migration enforces priority 1–1000, timeout 10–900 and object-shaped request settings in PostgreSQL. It keeps the previously tested model-field migration unchanged. Invalid encryption settings produce one JSON error line and a non-zero exit before the application binds a port.


# Test connection (section 16)

`POST /api/admin/models/{id}/test` is an administrator route on port 8080. It
returns 404 for a missing/removed entry and 409 `no_key` when no key is saved.
Otherwise it sends exactly the fixed OK request, pinned to this entry and
non-streamed, through the Gateway. Failure results use HTTP 200 with `ok: false`;
provider fields are explicitly null when absent. Missing service credentials
are a normal failed result and do not prevent application startup.

`CC_GATEWAY_URL` is supplied by the Control Centre ConfigMap.
`CC_CLIENT_SECRET` comes from optional Secret `control-centre-oidc`, key
`client-secret`. The token URL is `CC_OIDC_ISSUER` plus
`/protocol/openid-connect/token`, with fixed client ID `ooh-control-centre` and
credentials only in the form body. Tokens are cached until 30 seconds before
expiry. The HTTP limit covers token acquisition and the Gateway call and is
the entry timeout plus 10 seconds. The browser allows an additional five seconds.
The admin's subject is used only in the delegated `admin-test-` user ID, never
in request logs.

Every attempted existing-entry test, including no-key and no-credential failures,
appends one `model.tested` audit row and the usual `audit.events` outbox message.
The target is `model_id`; detail is exactly `{model_entry_id, ok, reason,
duration_ms}`. Reply text, provider messages and keys are not logged or audited.
Only a fixed setup-error log is written if service authentication fails.
Provider text is additionally redacted before returning it to the browser;
full keys, shared runs of at least eight characters and sk-style key strings
are removed. Provider messages are capped at 300 characters.

**Prepare service credentials.** Type this in your harness terminal, in the
plain shell; Claude runs it while Aziz watches. No password is needed. This
copies the current Control Centre credential inside Keycloak to the application
Secret once. Run realm sync first. Good result: `DONE`. A changed existing
credential is a `STOP:`; ask the maintainer before replacing it.

```bash
cd ~/projects/worktrees/stage-3
install/71-control-centre-oidc.sh
```

The deployment order is 35 → 71 → 65 → 61 → 69 → 70, as described in the root
README. Script 61 warns when the optional credential Secret is absent; it does
not stop for it. If 71 reports missing tools, finish server setup. If it cannot
read Keycloak credentials, check the Keycloak pod's readiness and bootstrap
access privately. If the Secret differs, 71 retains it and reports the change.
Never display or paste secret contents.

**Load credentials after a late setup.** Type this in your harness terminal,
in the plain shell; Claude runs it while Aziz watches. No password is needed.
The folder does not matter. Use this only when the Control Centre was already
running without the Secret when 71 created it. This replaces the pod so it
reads the newly available environment setting. Good result: the replacement pod
becomes Ready and connection tests no longer report missing credentials.

```bash
kubectl -n ooh-apps rollout restart deployment/control-centre
```

The model tests use a fake Gateway and token endpoint; the builder makes no
paid calls. Follow the Quick Guide's .NET checks and finish with
`dotnet build-server shutdown`.


# Request access (section 17)

The new `AccessRequests` migration creates `access_requests`, its unique user-ID
key and status constraint, paging index, application grants and no-removal
trigger. The app role has SELECT/INSERT/UPDATE only; both owner and app role are
blocked from hard deletion and truncation. `deleted_at` is unused in Stage 2.
No earlier migration was edited.

The backfill approves people first seen before the migration transaction and
active user grants created before it. It waits for existing people/grant writes,
uses a stable transaction timestamp cutoff and writes one privacy-limited
`access.approved` audit plus the normal `audit.events` outbox entry per new row.
`decided_by` is `migration`. Everyone alone does not grandfather an unknown user.

`POST /api/access/observe` is Harness-service-only. It requires the exact
verified user `sub` as `user_id` and verified `is_admin`; optional name/email/
organisation/access_reason may be null. Strings are trimmed, then validated at
200/320/100/300 characters respectively. User IDs are never trimmed or folded.
A missing row becomes pending unless there are already 100 pending rows, when
it returns `closed` without creating or auditing a row. A repeat is idempotent;
profile changes are copied and audited only while pending. Non-admin observation
cannot change an approved or rejected status. Verified admins are automatically
approved with `decided_by system:admin-role`; human admin observation in
`People.Observe` has the same effect, including after a revoke.

All three rights paths check approved access before grants: Decision, rights/me
and skills. Missing, pending, rejected and soft-removed access rows receive
nothing, including Everyone. Adding a user grant approves access in the same
transaction and can reapprove a rejected person. An existing active user grant
is reused with HTTP 200; a new grant returns 201. Everyone duplicates still
return 409. No Keycloak lookup is performed.

Admin access-request routes provide newest-first filtering/paging, pending-only
counts, Approve, Reject and Revoke. The list/count hide `stage-check-` identities.
Approve requires an existing positive chat-tier right, creates no duplicate
grant and conflicts if already approved. Reject acts on pending requests;
Revoke acts on approved requests and records `access.revoked`. Both set rejected
status. Rejected requests can be approved later. Existing grants are retained
and gated by status, rather than removed by rejection/revocation.

A transaction-scoped PostgreSQL advisory lock serializes admission changes,
including the pending-cap check, automatic/manual approval and grants. Status
changes and audit/outbox writes commit together. Access audit detail contains
only user_id, status, decided_by and approved_tier, never profile fields,
passwords or tokens. Pending profile changes use `access.requested` as well.

The admin screen and operator steps are described in the Admin Console README.
The combined deployment order is 61 → 67 → 35 → 68 → 69 → 62 → 70. Builders do
not run these deployment/check scripts. Check 62 reuses `stage-check-access`,
creates or reuses an Everyone grant on reserved tier 99, proves that pending
users get nothing and approved users get tier 99, then removes the grant.
Reserved check requests are hidden from the list/count but remain protected
business rows. The waiting cap counts all pending rows, including check rows.
If the check user cannot remain pending, inspect the waiting cap and reserved
identity before retrying; never delete requests or audit rows.

Run the existing .NET and contract checks from the Quick Guide. The database
suite includes backfill boundary checks, atomic concurrent admission at the
100-request boundary, status/grant behavior, audit privacy and owner/app-role
no-removal checks. Test requests left pending are rejected through audited
cleanup; no test data is deleted. End checks with `dotnet build-server shutdown`.


# Rows 15–16: model titles

`GET /api/rights/me` always includes `chat_tier_titles`, an object keyed by the
allowed chat tier as a string. For each tier it selects an active main chat
entry by lowest priority, then earliest creation time; entry ID breaks exact
ties. Backup entries and removed entries cannot supply picker titles. A tier
with no active main entry has no map key, so the Workspace can show just its
tier number. Unapproved users receive an empty map along with no rights.
The map contains titles only, never registry addresses or credentials. It names
the preferred main entry for the picker; the actual answering model remains
the truth in the answer metadata when a backup is used.

Row 16's reply-language system message is owned by Part B; the Control Centre
does not add or log a system prompt. No model is called to choose a title here.

# Thinking settings and model requests (rows 19–22)

The forward `ThinkingAndTierRequests` migration adds nullable JSONB
`request_settings_thinking_off` and the protected `tier_requests` table.
SQL NULL means no thinking-off switch; an object, including `{}`, means a switch
is configured. Arrays, scalar JSON and JSON null are refused by the database.
Admin writes accept JSON null to clear the column and omit it to retain its
value. Admin and Gateway registry answers always include the field.

`/api/rights/me` returns `chat_tier_thinking_switch` using exactly the same active
main entry as `chat_tier_titles` (priority, creation time, ID). The actual answering
model may differ after failover. `requestable_tiers` includes only tiers with an
active main entry, excluding 99 and every active user or Everyone grant. Latest
request state is `pending`, `rejected`, or null. All three fields are empty for
people whose access is not approved; provider settings and addresses stay private.

Only the Harness service account may submit `/api/tier-requests` for an approved
person. Reasons are optional, trimmed and limited to 300 characters. One pending
request per person/tier is protected by a partial unique index. Requests serialize
with admission and grants; at most 20 can be pending per person. A rejected tier
can be requested again seven days after its decision. Admission, eligibility,
duplicate and cap failures use the codes declared in the HTTP contract.

Administrators list model requests with `status`, `limit` and `after`, count pending
requests and approve or reject a pending request. Approval reuses an active user
grant or creates one, with the decision, grant and audit in one transaction. Both
decisions return `409 not_approved` if access has been revoked; approve access
before deciding that model request. Lists, counts and decisions hide reserved
`stage-check-` users. Missing profile name or email falls back to the user ID.
Reasons never enter audit detail, outgoing audit events or logs. Table DELETE and
TRUNCATE are refused for both database roles; old migrations remain unchanged.
The automated tests exercise these rules using the isolated test database and
fake identity tokens; they make no provider calls.

# Stage 3 administration

The same deploy command applies the new service addresses and the forward
`SkillsAndOperations` migration. Existing migrations are unchanged. Builders run
only the local checks above. Deployment, browser checks and reboot checks belong
to the merged stage run described in the repository Quick Guide.

Type this in your harness terminal, in the plain shell. No password is needed.
This builds the Control Centre and runs its tests without compiler daemons.
Good result: zero warnings or errors, then every test passes.

```bash
cd ~/projects/worktrees/stage-4-part-d/services/control-centre
DOTNET_CLI_USE_MSBUILD_SERVER=0 dotnet build --disable-build-servers -p:UseSharedCompilation=false -warnaserror
DOTNET_CLI_USE_MSBUILD_SERVER=0 dotnet test --no-build
```

Type this in your harness terminal, in the plain shell. No password is needed.
This checks formatting and the migration snapshot without applying migrations.
The connection below is an unused, local tooling placeholder, with no password.
Good result: no formatting changes and no pending model changes.

```bash
cd ~/projects/worktrees/stage-4-part-d/services/control-centre
DOTNET_CLI_USE_MSBUILD_SERVER=0 MSBUILDDISABLENODEREUSE=1 UseSharedCompilation=false dotnet format --verify-no-changes --no-restore
CC_DB_MIGRATE_CONNECTION='Host=127.0.0.1;Database=controlcentre_test' DOTNET_CLI_USE_MSBUILD_SERVER=0 dotnet ef migrations has-pending-model-changes --project ControlCentre --no-build
```

The new migration creates protected `skill_requests` and insert-only
`dead_letters`, adds model health reason/time and service-account markers to
people and access rows. The application cannot update dead letters; owner and
application roles cannot remove or truncate either new table. Rollbacks refuse
data removal. Test settings remain private and point only at `controlcentre_test`.

Skill requests follow model-request admission: approved access, an active skill
whose manifest right is missing, one pending request per user/skill, at most 20
pending requests per user, and seven days after rejection. Decisions and grants
share the access advisory lock and database transaction. Request reasons never
enter audit rows or logs. Requestable skill rows always include `requested`, even
when null. Skill rights come from the manifest. Access-request audits use `skill.access_requested`,
`skill.access_approved` and `skill.access_rejected`, keeping job-count action
`skill.requested` exclusive to job requests.

One Kafka consumer in group `control-centre` subscribes to `approvals.requested`
and all six contract dead-letter topics. Dead letters are deduplicated by their
broker topic, partition and offset, including unreadable messages. Their original
content is available only through administrator routes and is never logged. A
storage failure leaves the broker offset uncommitted. Administrators can replay through the Stage 4 route described below.
Approval creation and decision audits contain only IDs, action, risk, status,
decider and note; the safety excerpt remains in the approval itself.

Only the Gateway can report model health, using port 8081. The public port returns
404. Health reasons accept only `timeout`, `connection`, or `http_<status>` codes.
Admin model views include `health`, `health_reason` and `health_changed_at`.
Classification connection tests use the fixed `/v1/classify` question in the
stage spec, pinned to the selected model entry; a successful result includes
`score`. Other test behavior and redaction are retained. Test buttons make a
short paid call; automated tests use fake endpoints only.

The in-memory health poller checks six service health routes, Kafka metadata and
Keycloak discovery every 30 seconds with five-second request limits. Configuration
uses `CC_HARNESS_API_URL`, `CC_GATEWAY_URL`, `CC_SLIDES_WORKER_URL`,
`CC_AUDIT_WRITER_URL`, `CC_COST_METER_URL`, `CC_SAFETY_WATCHER_URL`, and the existing
issuer/Kafka settings. No health table exists.

Overview obtains counts, costs and trail rows through the audit writer and cost
meter HTTP contracts, using the Control Centre's cached service token. The agreed
day for every Overview figure is the display-zone day. Part B currently requires
`day=YYYY-MM-DD` (UTC), so helper figures temporarily retain that query until its
range support exists. The coordinated replacement is
`GET /v1/counts?from=<ISO UTC>&to=<ISO UTC>` and
`GET /v1/costs?from=<ISO UTC>&to=<ISO UTC>`, using the display-zone day's UTC
start and end, half-open `[from, to)`, with unchanged response shapes. Realm sync
must add the two custom audiences to that client. A missing credential, timeout,
refused request or unavailable helper leaves its figures null; the other helper
still supplies its figures. Approved people come from local approved access rows;
active people are always a non-null count from the Control Centre's own active
people rows with a non-deleted approved access request, whose
`last_seen_at` falls within today in `CC_DISPLAY_TIME_ZONE` (first value
`Asia/Kuala_Lumpur`). Service markers and `stage-check-`, `service-account-`,
`admin-test-` and `title-` identities are excluded. The first observation after
local midnight refreshes the sighting even within the hourly throttle.
Dead-letter attention counts only the last 24 hours and uses the newest matching
row's `received_at`, never the Overview request time. Trail filters are validated before
proxying. The proxy enriches trail rows with `person` from local known names,
then email, retaining `user_id` for diagnostics. Every administration route
requires an administrator token.

`CC_DISPLAY_TIME_ZONE` is the authoritative IANA display-zone setting. Admin
responses carry `X-Display-Time-Zone`; the console formats dates and the named
Overview greeting in that zone. The signed-out greeting follows browser time.
The chiseled runtime omits time-zone data, so the Docker build copies
`/usr/share/zoneinfo` from the existing pinned SDK image. No package or image
version is added or changed. This follows Microsoft's documented
[container globalization requirements](https://learn.microsoft.com/en-us/dotnet/core/docker/container-images).

After editing the display-zone ConfigMap and applying it through the existing
deploy script, load the setting into a replacement pod. Type this in your harness
terminal, in the plain shell; Claude runs it while Aziz watches. No password is
needed; the folder does not matter. This restarts the Control Centre and waits
for Ready. Good result: the rollout finishes successfully.

```bash
kubectl -n ooh-apps rollout restart deployment/control-centre
kubectl -n ooh-apps rollout status deployment/control-centre --timeout=600s
```

The Harness passes `is_service_account` from its verified token. The Control
Centre stores that marker on access and people rows. Its own token observation
uses the presence of `client_id` or a `preferred_username` beginning with
`service-account-`. People and waiting-decision lists exclude those identities
and reserved check users in normal lists and counts. An administrator can still
retrieve any active approval by `correlation_id` or by its approval ID, regardless
of its requester. The badge continues to count only the normal pending list, and
Overview continues to hide those requesters. Dead-letter diagnostics retain all
requesters; the trail proxy forwards explicit correlation and user filters without
requester filtering. Script 62 uses the explicit correlation lookup unchanged.
Display profiles fall back to the access request;
observe does not copy profiles into its audit rows.

No dependency was added. The new Kafka calls use the existing Confluent.Kafka
2.16.0 package. On 11 Nov 2026, `GetMetadata(TimeSpan)`, broker metadata and
`ConsumeResult.Topic/Partition/Offset` were checked against Confluent's official
[IAdminClient reference](https://docs.confluent.io/platform/current/clients/confluent-kafka-dotnet/_site/api/Confluent.Kafka.IAdminClient.html)
and [ConsumeResult reference](https://docs.confluent.io/platform/current/clients/confluent-kafka-dotnet/_site/api/Confluent.Kafka.ConsumeResult-2.html).
This Part sends no provider requests and introduces no provider field names;
classification test fields follow the Gateway contract. Provider adapter field
verification belongs to Part B.

# Stage 4 tracing and replay

`OTEL_EXPORTER_OTLP_ENDPOINT` enables tracing; an empty or missing value registers
no tracer provider or exporter. The ConfigMap supplies the service name, HTTP
protobuf protocol and parent-based always-on sampler. Export uses a batch
processor and a five-second timeout, outside the request path. No database spans
are collected. The health routes and health poller's requests are excluded.
Outgoing calls to our services and Keycloak are marked for instrumentation;
Jaeger queries and other addresses are excluded. Ingress requests identified by
`X-Forwarded-For` ignore incoming trace context. Internal requests retain it.

A processor keeps only the exact Stage 4 section 8 tag keys, removes every event
and clears status descriptions unless an error code is available. .NET 10 has no
public event-removal method, so the processor clears Activity's runtime event
list before the exporter; tests exercise this against the pinned runtime.
Kafka sends and consumers propagate W3C headers. Outbox rows retain traceparent
and tracestate, and their eventual send spans continue the originating trace.
Audit event payloads include a valid current trace ID when present.

The forward `TracingAndReplay` migration adds the outbox context and append-only
`dead_letter_replays`. Its triggers forbid update, delete and truncate for both
roles; the application receives SELECT and INSERT only. Rollback refuses data
removal. Failed approval deliveries no longer become processed event IDs. Broker
redeliveries deduplicate by a stable outbox ID based on topic and broker position;
a newly published replay can process the original approval event.

The admin trace proxy validates the trace ID and reduces Jaeger's v3 OTLP JSON
into sorted spans, allowing only the section 8 attributes. Its fixture is copied
from [Jaeger 2.23.0's own GetTrace snapshot](https://github.com/jaegertracing/jaeger/blob/v2.23.0/cmd/jaeger/internal/extension/jaegerquery/internal/apiv3/snapshots/GetTrace.json).
Tests use that exact snapshot plus synthetic service, timestamp and attribute
fields to exercise conversion and filtering. Unknown traces return
`404 trace_not_found`; failed or missing Jaeger returns `503 tracing_unavailable`.
Audit rows continue to load independently. `trace_id` is forwarded as a trail
filter and preserved on trail rows.

Replay publishes the stored message unchanged to its source topic and waits for
delivery. The original event ID and correlation key remain unchanged; trace
headers come from the administrator's replay request. A successful replay
returns `202 sent`; Kafka failure returns `503 kafka_unavailable` and records a
failed replay row. Both outcomes append the `dead_letter.replayed` audit action
with IDs and topic only. Unknown IDs return 404. Chat dead letters and non-JSON
originals return `409 not_replayable`. A JSON original also needs its original
request ID to preserve the Kafka key; a missing or invalid ID is refused.
The dead-letter list adds replay count,
last replay time, replayability and replay history without modifying the letter.

New direct packages, each pinned to 1.21.0 and checked on NuGet on 12 Nov 2026:
[OpenTelemetry.Extensions.Hosting](https://www.nuget.org/packages/OpenTelemetry.Extensions.Hosting/1.21.0)
for host integration,
[OpenTelemetry.Instrumentation.AspNetCore](https://www.nuget.org/packages/OpenTelemetry.Instrumentation.AspNetCore/1.21.0)
for server spans,
[OpenTelemetry.Instrumentation.Http](https://www.nuget.org/packages/OpenTelemetry.Instrumentation.Http/1.21.0)
for internal HTTP spans, and
[OpenTelemetry.Exporter.OpenTelemetryProtocol](https://www.nuget.org/packages/OpenTelemetry.Exporter.OpenTelemetryProtocol/1.21.0)
for batch OTLP HTTP export. Tests use a local in-memory exporter class, with no
additional package. No UI dependency or container image version changes.
