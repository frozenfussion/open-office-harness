# QUICK GUIDE

1. Type this in your harness terminal, in the plain shell. This creates the Gateway databases and private settings. No password is needed. Claude runs setup and deployment in the shell tile while Aziz watches.

   ```bash
   cd ~/projects/worktrees/stage-2-part-a
   install/64-model-gateway-setup.sh
   ```

   Good result: `DONE`. Test settings stay outside the repository in `~/.config/ooh/model-gateway-test.env`, mode 600. After the Parts merge, use `cd ~/projects/worktrees/stage-2` instead; after acceptance, use `cd ~/projects/open-office-harness`.

2. Do this in the GitHub package settings in your PC browser, after the first green Model Gateway image workflow. Open the package settings link below and choose **Change visibility → Public**. This lets the cluster pull the image without signing in. Good result: the package says Public.

   [Model Gateway package settings](https://github.com/users/frozenfussion/packages/container/ooh-model-gateway/settings)

3. Type this in your harness terminal, in the plain shell. This deploys the image for this checkout and waits for its migration and new pod. No password is needed. First deploy the Control Centre changes as the root guide describes.

   ```bash
   cd ~/projects/worktrees/stage-2-part-a
   install/65-model-gateway-deploy.sh "$(git rev-parse --short=12 HEAD)"
   ```

   Good result: `Running image: ...` and `DONE`. The 12-character tag must belong to a green image workflow. For a merged checkout whose image has not built, run the Model Gateway image workflow on that branch first.

4. Type this in your harness terminal, in the plain shell. This shows the pod and its image. No password is needed; the folder does not matter for this command.

   ```bash
   kubectl -n ooh-apps get pods -l app=model-gateway -o wide
   kubectl -n ooh-apps get deployment model-gateway -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
   ```

   Good result: one Ready pod and the intended image tag. Requests are 100m CPU / 128Mi memory for both migration and app; limits are 1 CPU / 512Mi. Actual live use is checked after deployment.

5. Type this in your harness terminal, in the plain shell. This reads recent application logs. No password is needed; the folder does not matter for this command.

   ```bash
   kubectl -n ooh-apps logs deployment/model-gateway -c model-gateway --since=10m
   ```

   Good result: JSON lines without prompts, answers, keys or tokens.

   Type this in your harness terminal, in the plain shell, if migration failed. It reads migration logs. No password is needed; the folder does not matter for this command.

   ```bash
   kubectl -n ooh-apps logs deployment/model-gateway -c migrate
   ```

   Good result: a JSON line saying migrations completed, or a clear failure without credentials.

6. Type this in your harness terminal, in the plain shell. This restarts the Gateway. No password is needed; the folder does not matter for this command. Claude runs it while Aziz watches.

   ```bash
   kubectl -n ooh-apps rollout restart deployment/model-gateway
   kubectl -n ooh-apps rollout status deployment/model-gateway --timeout=600s
   ```

   Good result: rollout completed. After a reboot Kubernetes starts it automatically; allow five minutes, then use the status step and the root guide's stage check.

7. Type this in your harness terminal, in the plain shell. This stops the Gateway without deleting data. No password is needed; the folder does not matter for this command. Claude runs it while Aziz watches.

   ```bash
   kubectl -n ooh-apps scale deployment/model-gateway --replicas=0
   ```

   Good result: deployment scaled.

   Type this in your harness terminal, in the plain shell. This starts the Gateway again. No password is needed; the folder does not matter for this command. Claude runs it while Aziz watches.

   ```bash
   kubectl -n ooh-apps scale deployment/model-gateway --replicas=1
   ```

   Good result: deployment scaled; the status step shows one Ready pod.

8. Type this in your harness terminal, in the plain shell. This runs the builder checks with fake providers and the isolated test database. No password is needed. Run setup first; never print or paste the private settings.

   ```bash
   cd ~/projects/worktrees/stage-2-part-a/services/model-gateway
   set -a
   source ~/.config/ooh/model-gateway-test.env
   set +a
   uv run ruff check
   uv run ruff format --check
   uv run pytest
   ```

   Good result: all checks pass, with no database tests skipped. The test migrates only `modelgateway_test`; protection checks run as owner and application roles inside rolled-back transactions. Without the settings it skips the database tests and says why. The pinned framework emits a TestClient deprecation warning; no extra dependency is added for it.

9. Type this in your harness terminal, in the plain shell. This checks the contracts and scripts without changing the cluster. No password is needed.

   ```bash
   cd ~/projects/worktrees/stage-2-part-a
   uv run --project contracts/check pytest contracts/check/tests
   bash -n install/64-model-gateway-setup.sh install/65-model-gateway-deploy.sh
   shellcheck install/64-model-gateway-setup.sh install/65-model-gateway-deploy.sh
   ```

   Good result: 17 contract tests pass and the shell checks print no errors. The explicit test folder keeps the contracts environment from collecting unrelated service tests.

## What the Gateway does

The Harness service account (`azp: ooh-harness-api`) with a valid realm signature, issuer, audience, expiry and subject can call `/v1/call` and `/v1/classify`. The Control Centre service account may call `/v1/call` only for the fixed test described below; it cannot classify. `/health` is public and checks the database. Classification validates its input and returns `not_built_yet` until Stage 3. Interactive API documentation routes are disabled.

The Control Centre supplies all model addresses, IDs, keys, prices and settings. Its registry response must include `model_entry_id`, `created_at`, title, purpose, tier, role, priority, connection type and the configured limits. The spec author agreed to expose `created_at` on 10 November 2026 so the Gateway can order equal-priority entries itself. Part D owns that response.

The Gateway caches registry replies for 30 seconds, decrypted keys for 60 seconds and service tokens until 30 seconds before expiry. Expired cache entries are never used when a refresh fails. A missing key for an entry without a key allows a keyless on-prem connection. Redirects are refused, so provider credentials stay at the configured address.

Active supported entries are tried main first, then backup, then priority ascending, then creation time. A pinned `model_entry_id` must match the active purpose and tier and never fails over. Unknown signing key IDs trigger at most one realm-key refresh every 30 seconds, including concurrent requests and failed refreshes. Registry failures log only their reason class and HTTP status; server logs retain logger, message class and exception type without raw exception text.

Rate checks count only `ok` and `failed` rows for the same entry and user over the last 60 seconds. Budget checks sum the entry's costs since midnight UTC; zero budget means no limit. Skips are recorded with zero cost. Costs use decimal arithmetic, rounded to the database's six decimal places. A call still streaming has no usage row yet.

Before the first text or tool event, a failed connection can move to the next entry. After output, failure emits `failed` and ends the answer. Disconnection closes the provider stream and records a failed attempt. Usage is append-only for owner and application roles. The application can only SELECT and INSERT; migrations run as the owner in an init container, with an advisory lock and numbered migration ledger.

Each SSE `data:` line contains one JSON object (`delta`, `tool_call`, `completed`, `failed`); no `event:` line is used. Both stream headers prevent buffering or caching. Non-streamed calls collect text, tools, selected entry metadata, usage and cost into one JSON response.

Extra request settings replace top-level fields after the adapter builds the request; `null` removes a field. They must be a JSON object. Newer Anthropic versions may refuse `temperature`, `top_p` or `top_k` supplied here. The two compatible connection formats impose no length limit unless configured; the Messages format defaults to 4096 output tokens.

## Visible thinking (Rows24-26, Gateway row 24)

When a provider returns visible thinking text, the Gateway emits `{"type":"thinking","text":"..."}` SSE events before or between answer deltas, followed by the usual completed event. Non-streamed answers include a separate `thinking` string, or null when no non-empty thinking arrived. Empty thinking strings are dropped. Signatures, encrypted reasoning and redacted blocks are never forwarded; thinking and answer text are never logged. Usage and cost still use the provider's token counts.

The chat-completions adapter reads `message.reasoning_content` or streamed `delta.reasoning_content`, falling back to `reasoning` when it is a non-empty string. Object forms and `reasoning_details` are ignored. This field was confirmed on 10 November 2026 against the [official provider guide](https://api-docs.deepseek.com/guides/thinking_mode/). The Messages adapter reads thinking blocks and `thinking_delta` text; configure `{"thinking":{"type":"enabled","display":"summarized"}}` in that entry's ordinary extra settings as the [official streaming reference](https://platform.claude.com/docs/en/build-with-claude/streaming) describes. The Gateway does not inject that setting. The Responses adapter forwards visible summaries when the final request settings ask for `reasoning.summary`: it maps `response.reasoning_summary_text.delta` and non-streamed reasoning items' `summary[].text` into thinking. It never forwards `encrypted_content`, raw reasoning events or duplicate done events. See the [official OpenAI streaming reference](https://developers.openai.com/api/reference/resources/responses/streaming-events).

Once any thinking has been streamed, a later failure ends the stream with failed rather than switching to a backup. Stored thinking is never sent back to a model; storing/displaying it belongs to the Harness and Workspace Parts. Unknown event types are ignored. Gateway usage rows contain counts and costs, never thinking; the Gateway sends no thinking to logs, audit or Kafka. No Gateway database migration, new dependency or deployment was performed for this update.

### Settings that enable visible thinking (Row 27)

Configure the following in the entry's ordinary extra request settings, with a placeholder model ID such as `example-model`. These are data; the Gateway does not inject them:

| Connection type | Example ordinary request settings |
|---|---|
| `openai_chat_completions` | On supporting services, `{"thinking":{"type":"enabled"}}` or `{"reasoning_effort":"high"}`. |
| `openai_responses` | `{"reasoning":{"summary":"auto"}}`. |
| `anthropic_messages` | `{"thinking":{"type":"enabled","display":"summarized","budget_tokens":1024},"max_tokens":2048}`. |

For manual thinking, `max_tokens` must be above `budget_tokens` in the same settings. A thinking block with no text is dropped. Deploy the Gateway first, then the Harness, then the Workspace; the merge operator performs deployment. Parts B/C own thinking storage caps, title-call behavior, history and display.

## Thinking switch (Row19)

`/v1/call` accepts optional boolean `thinking`, default true. The registry may supply `request_settings_thinking_off` as a JSON object; null or an absent field means there is no off switch. When thinking is false and this object is present, the adapter merges it over the body **after** ordinary `request_settings`. Top-level fields replace previous values, and null removes a field. An empty object is still a configured switch. When thinking is true or omitted, only the ordinary settings apply; the Gateway adds no provider-specific thinking field itself.

The completed SSE event and the non-streamed answer include `thinking_applied`, meaning the caller's choice was honoured: true for thinking on/default, true for thinking off when the answering entry has off settings, false for thinking off when it has none. The flag comes from the entry that actually answered after any failover. The Workspace can show "thinking off not supported by this model" for the last case.

Configure off settings by connection type in the Admin Console; use placeholder model IDs such as `example-model`, never a real model name in this repository:

| Connection type | Off-settings object |
|---|---|
| `openai_chat_completions` | For a service that supports it: `{"thinking":{"type":"disabled"}}` or `{"reasoning_effort":"low"}`. |
| `openai_responses` | `{"reasoning":{"effort":"low"}}`. |
| `anthropic_messages` | Leave empty when the model has no off switch. |

The Control Centre's fixed test call must omit `thinking`, including an explicit true value, and all other extra fields. Its default thinking choice remains on. This Gateway update needs no migration, dependency or settings change outside the registry entry. Automated checks use fake providers; no paid call is needed to test this behavior.

## Test connection (section 16)

In the Admin Console's Models & tiers screen, save a key and press **Test** beside that entry. Each click makes one short paid call, counts against that entry's rate limit and daily budget, and writes usage like a chat call. This builder's automated tests use fake providers only.

The Control Centre may send only a pinned, non-streamed call with the single user message `Reply with the single word OK.`, no tools, and a user ID starting `admin-test-`. Any other Control Centre call is refused with 403. The Harness rules are unchanged, including pinned checks.

On a failed test the Gateway adds `provider_status` and a scrubbed `provider_message` to its 503 response. Only the authorized Control Centre test receives these fields; Harness responses keep their ordinary error shape. Registry or budget errors have null provider details. Timeouts say `time limit reached`; connection failures say `could not connect`.

Each adapter reads at most 4 KiB of a non-success response, takes `error.message` when present or the text otherwise, removes the saved key, any matching key fragment of eight or more characters, and token-shaped `sk-` values, then limits the result to 300 characters. Provider messages and replies are never logged. Every failed provider attempt logs only `provider_failed`, entry ID, HTTP status (or null), and reason (`http`, `timeout`, `connect`, `bad_answer`). No new setup or database migration is needed for this Gateway change. The merged-stage guide owns the deployment order and the Control Centre/browser steps.

## Official reference check — 10 November 2026

Field names and event handling were checked against the official [chat completion reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create), [Responses streaming reference](https://developers.openai.com/api/reference/resources/responses/streaming-events), [Messages streaming reference](https://platform.claude.com/docs/en/build-with-claude/streaming) and [compatible Messages reference](https://api-docs.deepseek.com/guides/anthropic_api/). No behavior change from the stage spec was needed. The last reference calls `anthropic-version` ignored; it is still accepted, so the adapter keeps `2023-06-01` as required. Responses tools explicitly send `strict: false`.

## Images and filesystem

Python is pinned to 3.14.10. The build stage uses uv 0.13.7 pinned by registry digest; the run stage contains only Python, the production environment, application and SQL migrations. It runs as 10001, with bytecode writes disabled and stdout unbuffered. Both Kubernetes containers use a read-only root, dropped capabilities, no privilege escalation, and writable `/tmp` only. Local tests also run in a bubblewrap filesystem namespace with `/` read-only and `/tmp` writable. This checks application filesystem use; GitHub Actions builds the actual image and the live deploy checks it separately.

## STOP and HTTP errors

Scripts make no destructive database changes and can be rerun. Existing role passwords are preserved. Setup copies the sign-in secret without a trailing newline and refuses a changed existing copy.

| Message | What to do |
|---|---|
| `usage: install/...` | Use the exact command in the Quick Guide; deployment needs one 12-character tag. |
| `invalid deployment value ...` | Correct that value in `deploy/values/do.env` with the maintainer. |
| `missing tool ...` | Finish server setup; do not install packages from Codex. |
| `platform namespace missing` | Complete platform setup first. |
| `PostgreSQL is not Ready` | Inspect the database cluster and platform before retrying. |
| `existing ... secret has unexpected credentials` / `database passwords have an unexpected format` | Have the maintainer inspect the named Secret privately; do not print it. |
| `database resources are not ready` | Inspect the Database and DatabaseRole status, then rerun setup. |
| `PostgreSQL service has no valid ClusterIP` | Inspect Service `ooh-pg-rw`, then rerun setup. |
| `test database passwords have an unexpected format` | Have the maintainer inspect the test role Secrets privately. |
| `could not read Gateway client secret` / `Gateway client secret missing` | Inspect Keycloak readiness, bootstrap access and the existing Gateway client; then rerun setup. |
| `Gateway client secret changed` | Ask the maintainer before replacing the application copy. |
| `database setup failed` | Inspect PostgreSQL readiness and rerun setup; settings files are replaced atomically. |
| `image tag must be ...` | Use the first 12 hexadecimal characters of the image commit. |
| `image not built yet` | Run the Model Gateway image workflow for this commit. |
| `image not found or not public` | Check the workflow is green, then make the package Public. |
| `registry is unreachable` / `registry check failed` / `registry returned an invalid token` | Check registry availability and retry. |
| `required application secret missing` | Run the setup script. |
| `new Model Gateway revision is not Ready` / `current revision or migrations could not be verified` / `Model Gateway deployment failed` | Inspect migration logs, pod readiness and image visibility; rerun deployment. |
| HTTP 400 `invalid_input` | Supply the documented body; chat needs a positive tier. |
| HTTP 401 / 403 | Supply a valid token for the Gateway from the Harness service account. |
| HTTP 404 `no_model` | Add a supported active model for this purpose and tier; check any pinned entry. |
| HTTP 429 `rate_limited` | Wait a minute; no entry was called and at least one reached this user's rate limit. |
| HTTP 503 `budget_exceeded` | Every entry reached its daily budget; wait for tomorrow UTC or ask an admin. |
| HTTP 503 `registry_unavailable` | Inspect the internal Control Centre route and service credentials. |
| HTTP 503 `unavailable` | Inspect database readiness or model connectivity and retry. |
| HTTP 503 `not_built_yet` | Classification arrives in Stage 3. |

No cluster operation is run by the builder. Deployment, live provider calls, actual memory use and reboot checks belong to the merged stage run. Each run of `install/70-check-stage-2.sh` makes short paid calls to configured entries, including a stream per connection type in use.
