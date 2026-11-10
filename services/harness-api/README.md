# QUICK GUIDE

1. **Set up the databases and sign-in secret.**

   Type this in your harness terminal, in the plain shell. Claude runs it while Aziz watches. No password is needed. This creates the databases and saves private test settings. Existing credentials are kept.

   ```bash
   cd ~/projects/worktrees/stage-2-part-b
   bash install/66-harness-api-setup.sh
   ```

   Good result: `DONE`. Test settings are saved in `~/.config/ooh/harness-api-test.env`, mode 600. Never paste or print that file. For the combined stage deployment, use `cd ~/projects/worktrees/stage-2` instead; after acceptance use `cd ~/projects/open-office-harness`.

2. **Run the builder checks.**

   Type this in your harness terminal, in the plain shell. No password is needed. This loads only the private test database settings and checks the service. Run it after setup prints `DONE`.

   ```bash
   cd ~/projects/worktrees/stage-2-part-b/services/harness-api
   set +x
   set -a
   source "$HOME/.config/ooh/harness-api-test.env"
   set +a
   uv sync --frozen
   uv run ruff check .
   uv run ruff format --check .
   uv run pytest
   ```

   Good result: both Ruff checks pass and pytest has no failures or skips. Database protection checks run as the owner and app roles. Storage checks use a shared transaction that is always rolled back; a separate connection then verifies that none of that test user's conversations or messages remain. Without the two `HA_TEST_DB_*` settings, database checks are explicitly skipped; that is not a full pass.

3. **Deploy the image.**

   First wait for the Harness API image workflow to be green. Claude opens [package settings](https://github.com/users/frozenfussion/packages/container/ooh-harness-api/settings) on Aziz's PC; Aziz chooses **Change visibility → Public**. The workflow tests the image with a read-only root, without uv, as user 10001 before publishing it.

   Type this in your harness terminal, in the plain shell. Claude runs it while Aziz watches. No password is needed. This deploys the image for the current commit, runs migrations, and waits for that revision to be ready.

   ```bash
   cd ~/projects/worktrees/stage-2
   bash install/67-harness-api-deploy.sh "$(git rev-parse --short=12 HEAD)"
   ```

   Good result: `Running image: ...` and `DONE`. The image must have been built for that commit. For a different built commit, pass its first 12 hexadecimal characters. The old placeholder ConfigMap is removed only after readiness and migration success. Conversation data is kept.

4. **Check status and which image is running.**

   Type this in your harness terminal, in the plain shell. The folder doesn't matter for this command. No password is needed. This shows the image and ready replica count.

   ```bash
   kubectl -n ooh-apps get deployment harness-api -o wide
   ```

   Good result: one ready replica and the expected image tag.

5. **Read application logs.**

   Type this in your harness terminal, in the plain shell. The folder doesn't matter for this command. No password is needed. This reads recent JSON log lines.

   ```bash
   kubectl -n ooh-apps logs deployment/harness-api -c harness-api --tail=100
   ```

   Logs identify API failures with fixed event names and codes (and a tier for stream failures or budget fallback). Server log lines keep the logger name, a fixed message category and the exception type when available; exception messages and traceback text are excluded. They contain no prompts, answers, user IDs or credentials. Access logs are disabled.

6. **Read migration logs if deployment stops.**

   Type this in your harness terminal, in the plain shell. The folder doesn't matter for this command. No password is needed. This reads the current pod's migration result.

   ```bash
   kubectl -n ooh-apps logs deployment/harness-api -c migrate --tail=100
   ```

   Good result: `migrations_complete`. If it says `migration_failed`, inspect the database settings and readiness privately, then run deployment again. Do not edit an applied migration.

7. **Restart.**

   Type this in your harness terminal, in the plain shell. Claude runs it while Aziz watches. The folder doesn't matter for this command. No password is needed. This replaces the pod and reruns the safe migration check.

   ```bash
   kubectl -n ooh-apps rollout restart deployment/harness-api
   ```

   Repeat the status step until one replica is ready.

8. **Stop.**

   Type this in your harness terminal, in the plain shell. Claude runs it while Aziz watches. The folder doesn't matter for this command. No password is needed. This stops the API; its stored conversations stay in PostgreSQL.

   ```bash
   kubectl -n ooh-apps scale deployment/harness-api --replicas=0
   ```

   Good result: the Deployment is scaled. Chat is unavailable until started again.

9. **Start again.**

   Type this in your harness terminal, in the plain shell. Claude runs it while Aziz watches. The folder doesn't matter for this command. No password is needed. This starts the API again.

   ```bash
   kubectl -n ooh-apps scale deployment/harness-api --replicas=1
   ```

   Repeat the status step until one replica is ready.

10. **After a server reboot.** Allow five minutes, then check status. Kubernetes starts the API automatically if it had one replica before reboot. Claude runs the platform, Control Centre and Stage 2 checks while Aziz watches.

    Type this in your harness terminal, in the plain shell. No password is needed. This checks the combined stage after reboot.

    ```bash
    cd ~/projects/worktrees/stage-2
    bash install/40-check-platform.sh
    bash install/62-check-control-centre.sh
    bash install/70-check-stage-2.sh
    ```

    Good result: each prints only passing checks and ends with `DONE`. Each run of the Stage 2 check makes short paid model calls. Aziz then signs in to the Workspace and checks chat and history.

## STOP messages

Neither script needs sudo. Resolve the named problem and run the same script again; existing credentials and data are kept.

| STOP text | What to do |
|---|---|
| invalid deployment value | Correct the named setting in `deploy/values/do.env`. |
| missing tool | Finish server setup. |
| platform/apps namespace missing | Finish platform deployment. |
| PostgreSQL is not Ready | Inspect platform PostgreSQL readiness. |
| database resources are not ready | Inspect Database and DatabaseRole status. |
| existing secret has unexpected credentials / database passwords have an unexpected format | Have the maintainer inspect the Secret privately; do not replace it. |
| PostgreSQL service has no valid ClusterIP | Inspect Service `ooh-pg-rw`. |
| could not read Harness client secret | Inspect Keycloak readiness and bootstrap access, then retry. |
| Harness client secret changed | Ask the maintainer before replacing `harness-api-oidc`. |
| existing application database credentials differ | Ask the maintainer to inspect role and application Secrets privately before replacing anything. |
| database setup failed | Inspect PostgreSQL readiness and retry setup. |
| usage | Setup takes no arguments. Deployment takes at most one 12-character image tag. |
| image tag must be the first 12 characters | Supply the first 12 hexadecimal characters of a built commit. |
| image not built yet | Wait for the workflow for that commit, or run it on demand. |
| image not found or not public | Check the workflow is green; Aziz switches the package to Public. |
| registry is unreachable / registry check failed / registry returned an invalid token | Check registry availability and retry. |
| configuration hash could not be made | Check sha256sum is available and retry deployment. |
| required application secret missing | Run `install/66-harness-api-setup.sh`. |
| new Harness API revision is not Ready | Inspect migration logs, image visibility and pod status. |
| current revision or migrations could not be verified | Inspect the Deployment, its ReplicaSet and pods, then retry. |
| Harness API deployment failed | Inspect migration logs and pod readiness, then retry deployment. |

## API and storage

Every `/api` route requires a signed, unexpired Keycloak user token with audience `ooh-harness-api`, issuer `HA_OIDC_ISSUER` and non-empty `sub`. Health alone is public and checks PostgreSQL. Unknown inputs return `400` JSON without echoing the input. Files, uploads and job events return `503 not_built_yet` after authentication; Stage 3 builds them.

`GET /api/me` first observes the verified user's profile through the Control Centre, then reads rights and allowed skill titles. Its answer includes `access`: `approved`, `pending`, `rejected` or `closed` (new requests are temporarily full). The observe call uses the Harness service token and the exact user `sub`. Only the signed token supplies profile fields: name, email, organisation and access reason are trimmed and limited to 200, 320, 100 and 300 characters respectively; missing or non-string values become null. `is_admin` is true only when the verified token's `realm_access.roles` list contains `ooh-admin`. An observe failure or invalid status returns `503 rights_unavailable` before any rights call. The Control Centre owns approval and blocks grants for unapproved people; the Harness does not decide access. Other Harness routes are unchanged.

`GET /api/me` also returns the token's user ID and name, plus rights and allowed skill titles from the Control Centre. `chat_tier_titles` passes through the Control Centre's tier-to-title map, with string tier keys; the Workspace uses it for model names. The Control Centre selects the active main entry by lowest priority then creation time; no title is invented by the Harness, and a missing title falls back to the tier label in the Workspace. It also passes through `chat_tier_thinking_switch` and `requestable_tiers` from the Control Centre. Each requestable tier has a title and `requested` state (`pending`, `rejected` or null); the Control Centre excludes tier 99 and granted tiers and owns the seven-day rejection wait. No supplied body or query can change the user's ID. Conversations belong to that ID; other users see `404`. The conversation list orders by updated time, then ID, newest first. It defaults to 20 rows and accepts `limit=1..100`; `before` is the ID of an owned conversation from the preceding page (the spec author agreed to this pagination during the build).

Messages go to the Gateway as purpose `chat`, by tier, without any model identifier or provider setting. The optional `thinking` field is a strict boolean, default true; it is forwarded unchanged on the initial call and budget fallback. The Gateway reports whether the answering model applied the setting via required boolean `thinking_applied`; a missing or non-boolean value is an unexpected answer, never a default false. The lowest allowed tier is used when omitted. Rights are checked afresh for the selected tier and again before a budget fallback. Failed rights calls fail closed. Allowed skills are intersected with the user's rights; only locally bundled schemas become tools. The schema copy is tested byte for byte against the contract. A requested tool produces the fixed Stage 2 sentence, with the skill's title, followed by completion; no tool is executed.

Every streamed chat Gateway call prepends one system message from `HA_SYSTEM_PROMPT`, including budget fallback. The default is "You are the assistant in Open Office Harness. Always reply in the same language as the user's latest message." The ConfigMap `harness-api-config` supplies this setting; edit `deploy/apps/harness-api/configmap.yaml`, then run `install/67-harness-api-deploy.sh` with the existing image tag to update it without rebuilding the image. The deployment uses a hash of the rendered ConfigMap to restart the pod when settings change. A live ConfigMap edit is overwritten by the next deploy. An explicitly empty value sends no system message. The prompt is never logged or stored as a conversation message.

The history window is read before storing the new user message: the last 20 non-empty `completed` messages, oldest first, trimmed to start with a user message. The new question is appended once. A user's question is stored as `completed`; the initial title is its first 60 characters. After the first assistant answer stored as `completed`, and only while the conversation still has the default title, the Harness attempts one non-streamed title call on the tier that answered. Rights are rechecked for the original user, while the Gateway user ID is `title-<sub>` so the title does not consume that user's rate allowance; model budget and cost still count. A fixed 20-second limit covers the title work and the stream closes after the title call or that limit. It uses its own fixed title instruction instead of `HA_SYSTEM_PROMPT`, followed by the first question and the first completed answer (each cut to 2000 characters), with no tools. The returned title is trimmed, stripped of surrounding quotes and a final full stop, and cut to 60 characters. Updating the title leaves `updated_at` unchanged. Failure keeps the initial title and logs `title_failed` with a safe code, never title or conversation text. Later answers do not retry; failed and `tool_requested` answers do not trigger title generation. Assistant content is appended after streaming, including partial text with outcome `failed` after a broken stream or browser disconnect. Messages cannot be updated or removed, even as the owner. All tables refuse DELETE and TRUNCATE. The application role has only SELECT/INSERT on messages and SELECT/INSERT/UPDATE on conversations; it cannot edit the migration journal.

SSE uses JSON `data:` lines, without `event:` lines, and ends with `completed` or `failed`; when the first completed answer produces a title, one final `title` event follows `completed`, with `conversation_id` and `title`. JSON errors are returned before any stream byte. Responses set `Cache-Control: no-store` and `X-Accel-Buffering: no`. Completion includes message ID, tier, model title, token usage, `thinking_applied` and a nullable fallback note. The answer is complete at that event; a later title event can still arrive on the same stream. `thinking_applied` is passed through for live replies only; there are no new thinking columns in stored history. Conversation history includes outcome and metadata. Chat text is passed as text; the Workspace owns its rendering.

| Code | Browser message / action |
|---|---|
| `no_tier` | You have no chat tier yet. An admin can grant one. |
| `tier_not_allowed` | You don't have tier N. An admin can grant it. |
| `rights_unavailable` | Rights could not be checked. Try again. |
| `no_model` | No model is set up for tier N yet. An admin can add one. |
| `rate_limited` | You are sending messages too fast for tier N. Wait a minute. |
| `budget_exceeded` | Use the lowest allowed lower tier, with a note; otherwise: Tier N has used its daily budget. Try again tomorrow or ask an admin. |
| `unavailable` | The model did not answer. Try again. A storage failure says conversation storage is unavailable. |

`POST /api/tier-requests` accepts `{tier, reason?}` with a positive integer tier and optional string/null reason (at most 300 characters). It supplies the verified user ID and forwards the request with the Harness service token; callers cannot choose another user. Only the Control Centre decides eligibility. Success is 201 `{id,status:"pending"}`. Errors preserve status/code: 403 `not_approved`, 400 `tier_not_requestable`, 409 `already_requested`, 429 `too_many_requests`; unavailable or malformed Control Centre responses fail closed with 503 `rights_unavailable`. The reason is never logged. A rejected tier may be requested again after seven days and each user may have at most 20 pending requests, as enforced by the Control Centre.

## Configuration and builds

The ConfigMap supplies `HA_OIDC_ISSUER`, `HA_OIDC_AUDIENCE`, `HA_CLIENT_ID`, `HA_CONTROL_CENTRE_URL` (port 8080), `HA_GATEWAY_URL` and `HA_SYSTEM_PROMPT`. Secret `harness-api-db` supplies `HA_DB_CONNECTION` to the app and `HA_DB_MIGRATE_CONNECTION` only to the migration container. Secret `harness-api-oidc` supplies `HA_CLIENT_SECRET`. Keys stay in the Control Centre and never enter the Harness. Service tokens are cached until 30 seconds before expiry; realm signing keys are cached for five minutes and refreshed for an unknown key ID at most once every 30 seconds, including failed fetches. Outgoing redirects are refused.

Python is 3.14.10. The image uses `python:3.14.10-slim-trixie` for both stages; uv 0.13.7 is digest-pinned and present only in the build stage. The runtime uses user 10001, a read-only root, disabled bytecode writes and unbuffered stdout. `/tmp` is a bounded memory volume. The workflow builds, loads, checks the runtime, then pushes its 12-character commit tag. Runtime dependencies and all transitive versions are fixed in `uv.lock`.

The migration command applies numbered SQL files in order under a transaction advisory lock. SHA-256 checksums prevent changed applied migrations. It accepts only databases `harness` and `harness_test`; the journal is append-only. No Kafka, file storage, background task or real provider call is part of this service in Stage 2.
