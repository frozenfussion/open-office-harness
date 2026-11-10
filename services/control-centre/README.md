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

6. **Deploy, start, stop, restart, inspect logs, or recover after reboot.** Follow the repository's top-level README Quick Guide, maintained by Part B. The deployed service starts under Kubernetes; the builders do not start a server or change the cluster. The image takes `migrate` in its init container and serves port 8080 publicly and port 8081 internally in its main container. The Docker build context is `services/control-centre`.

If `dotnet` is missing or reports a different SDK, finish the home-folder SDK installation in the stage spec first; this package requires SDK `10.0.403`. If package restore fails, check network access and retry the build. If a database test fails to connect, finish Part B's database setup and rerun the tests. If a database test rejects the database name or role, rerun the setup script; do not substitute live settings. If migrations fail, retain their error message without connection strings for review; never edit a migration already applied. The service reads environment variables only and reports a missing variable by name, without its value.

# Control Centre

One ASP.NET Core deployable with Rights, Registry, Approvals, Audit and Platform modules. Environment variable names and deployment values are fixed in the Stage 1 spec, section 8. The running program gets `CC_DB_CONNECTION`; only migration mode reads `CC_DB_MIGRATE_CONNECTION`. The owner connection is not needed by the running service. JWT verification checks the signature, issuer, audience, expiry and subject. Health is the only public route. Unknown body fields, duplicate fields, unknown query fields and repeated query fields are rejected. Lists added in Stage 1 accept `limit` 1–200, default 50. People and rights are sorted by `user_id` and `key`; pass the last value as `after` for the next page. Admin models sort by `(purpose, tier, role, id)`; optional `after` is the last model entry UUID and continues that same order. The four existing contract routes retain their original input shapes.

Changes, audit rows and outgoing envelopes share one database transaction. Every HTTP request has one correlation UUID. People are created with a race-safe insert. Their email and name are written and audited only on create or change. The system timestamp `last_seen_at` is refreshed at most hourly, without an audit row. Approval decisions retain the requester's identity and correlation in `approval.decided`. The local audit detail holds before/after data; published audit events contain only actor, action, target and outcome.

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
cd ~/projects/worktrees/stage-2-part-d/services/control-centre
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
