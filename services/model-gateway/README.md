# QUICK GUIDE

1. Type this in your harness terminal, in the plain shell. This creates the Gateway databases, Kafka credential copy and private settings. First finish the platform and realm updates in the root guide. No password is needed. Claude runs setup and deployment in the shell tile while Aziz watches.

   ```bash
   cd ~/projects/worktrees/stage-3-part-b
   install/64-model-gateway-setup.sh
   ```

   Good result: `DONE`. Test settings stay outside the repository in `~/.config/ooh/model-gateway-test.env`, mode 600. After the Parts merge, use `cd ~/projects/worktrees/stage-3` instead; after acceptance, use `cd ~/projects/open-office-harness`.

2. Do this in the GitHub package settings in your PC browser, after the first green Model Gateway image workflow. Open the package settings link below and choose **Change visibility → Public**. This lets the cluster pull the image without signing in. Good result: the package says Public.

   [Model Gateway package settings](https://github.com/users/frozenfussion/packages/container/ooh-model-gateway/settings)

3. Type this in your harness terminal, in the plain shell. This deploys the image for this checkout and waits for its migration and new pod. No password is needed. First deploy the Control Centre changes as the root Stage 3 guide describes.

   ```bash
   cd ~/projects/worktrees/stage-3-part-b
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
   cd ~/projects/worktrees/stage-3-part-b/services/model-gateway
   set +x
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
   cd ~/projects/worktrees/stage-3-part-b
   uv run --project contracts/check pytest contracts/check/tests
   bash -n install/64-model-gateway-setup.sh install/65-model-gateway-deploy.sh
   shellcheck install/64-model-gateway-setup.sh install/65-model-gateway-deploy.sh
   ```

   Good result: all contract tests pass and the shell checks print no errors. The explicit test folder keeps the contracts environment from collecting unrelated service tests.

## Gateway behavior

The internal Gateway serves `/v1/call` and `/v1/classify`. All routes except `/health` verify Keycloak signature, issuer, audience, expiry and subject. Interactive docs are disabled. The Harness may use either route; the Slides worker may make non-pinned, non-streamed calls; the safety watcher may classify. The Control Centre may only make the fixed pinned connection tests. For classification its `user_id` must equal `admin-test-<verified sub>`, its text must be `This is a connection test.` and its questions must be `{"test":"Is this a connection test?"}`. Other callers receive 403.

The Control Centre supplies every provider address, model ID, key, price and request setting. Registry replies are cached for 30 seconds, keys for 60 seconds, and service tokens until 30 seconds before expiry. Failed refreshes never use expired cache values. Redirects are refused. Active entries are tried main before backup, then priority and creation time. Pinned calls never fail over. Failure after any visible output ends the stream. Entry rate limits and daily UTC budgets use the existing append-only usage table, including classification. Zero budget means unlimited; cost uses decimal arithmetic rounded to six places.

`POST /v1/classify` accepts text (1–20000 characters), 1–10 named questions, `user_id` and optional `model_entry_id`. Question keys match `^[a-z][a-z0-9_]{0,39}$`. It returns `scores`, entry ID/title, input/output usage and `cost_usd`. A `jev_systemone` entry uses its typed decision endpoint; each chat adapter requests exactly one JSON object of probabilities. Extra score keys are ignored. A missing, boolean, nonnumeric or out-of-range score fails the entry and tries the next one. Classification uses purpose `classification` without a tier.

Every authorized call publishes one `audit.event` to `audit.events`, keyed by the UUID in `X-Correlation-Id` (a new UUID when absent). Payloads contain actor, action, purpose/tier target, outcome, entry ID/title when known, usage/cost, and classification scores. They contain no prompts, answer text, provider reasoning or keys. Kafka delivery failure logs a fixed JSON message and does not fail the model call. Health transitions report `ok` or `down` to the Control Centre's private port; pre-output errors use `timeout`, `connection` or `http_<status>`. Repeated unchanged health is not reported. A failed report is logged without its body and is tried again on the next state change.

## Tool messages and private reasoning

A history message may be an assistant with `tool_calls: [{id,name,arguments}]` and `reasoning_state`, or a tool result with `tool_call_id` and string content. `tool_choice: {"name":"..."}` selects an offered tool, and `"none"` disables tools. For manual thinking modes that reject named forcing, the adapter uses auto and returns `tool_choice_applied: false`. Otherwise it is true. Follow-up calls inside a tool turn stay pinned to the first answer's entry ID.

Every completed answer returns an opaque `reasoning_state` object containing `model_entry_id`, also when no tool was used. The spec author's binding 11 November clarification permits the Harness to store this state privately in `messages.reasoning_state` and replay it across turns. It must never appear in a browser route, log or Kafka message. The Gateway itself does not persist it. Each adapter applies a history message's state only for the matching entry ID; a foreign state is dropped without error. Provider state is sent only to that entry's configured provider.

Chat Completions replays `reasoning_content` when the provider returned a string, plus standard function tool calls and tool result messages. A provider that returned no reasoning produces state containing the entry ID only; the adapter does not invent reasoning. Messages replays the complete content-block order, including thinking signatures and redacted blocks, then user `tool_result` blocks. Responses sets `store: false`, requests `include: ["reasoning.encrypted_content"]`, and replays all returned output items before `function_call_output`. Streaming preserves completed blocks/items as well.

Visible thinking is separate from private state: `thinking` SSE events contain visible text only; non-streamed responses have a separate `thinking` string or null. Empty text is dropped, and separate thinking blocks have paragraph breaks. Responses visible summaries require effective `reasoning.summary` settings. Raw state stays inside `reasoning_state`, never in answer or visible-thinking fields. Unknown provider events are ignored. The Harness owns storage and browser filtering.

Ordinary `request_settings` replace top-level provider fields and remove fields set to null. When the caller sets `thinking: false`, a configured `request_settings_thinking_off` object merges last. `thinking_applied` is true for on/default or a configured off-settings object; otherwise false. Model-specific controls remain registry data. Manual thinking may need both `thinking.budget_tokens` and a larger `max_tokens` in those settings. The Control Centre's chat test must omit `thinking` and all other extra fields.

## Official reference check — 11 November 2026

| Connection | Official fields checked and result |
|---|---|
| Chat Completions | [Create completion](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create): `messages`, assistant `tool_calls` with `type:function` and JSON-string arguments, tool `tool_call_id`, named function `tool_choice`, `auto`, `none`, `stream_options.include_usage`, token usage. |
| Compatible thinking | [Thinking guide](https://api-docs.deepseek.com/guides/thinking_mode/) and [API reference](https://api-docs.deepseek.com/api/create-chat-completion/): `reasoning_content`, `thinking.type`, streamed deltas, tool calls and usage. The guide requires reasoning from all earlier turns with tools; this prompted the binding retention clarification. Named forcing is refused in thinking mode, so explicit `thinking.type:enabled` uses auto. The reference calls reasoning nullable; neither official page specifies a required empty-string fallback for history from another entry. Such history therefore omits unmatched reasoning rather than fabricating it; no real-provider fallback claim is made. A returned empty string is preserved. |
| Messages | [Messages reference](https://platform.claude.com/docs/en/api/messages) and [thinking workflows](https://platform.claude.com/docs/en/build-with-claude/thinking): ordered thinking/signature and redacted blocks, `tool_use`, user `tool_result`, `tool_use_id`, `tool_choice` auto/tool/none, `thinking_delta`, `signature_delta`, usage and `anthropic-version`. Manual thinking refuses named forcing; adaptive thinking supports it. The adapter only downgrades explicit manual `thinking.type:enabled`. |
| Responses | [Create response](https://developers.openai.com/api/reference/resources/responses/methods/create) and [reasoning guide](https://developers.openai.com/api/docs/guides/reasoning): `store:false`, `include:reasoning.encrypted_content`, output reasoning/message/function_call items, `call_id`, `function_call_output`, named function and none choices, completed output items and token usage. No forcing restriction for reasoning was found. |
| Typed classification | [System One reference](https://docs.typesafe.ai/api/system-one): `/v1/systemone`, optional configured bearer key, `model`, `state`, `questions[key].type:noul`, `instructions`, `answers[key].noul`, `usage.input_tokens/output_tokens`. The hosted reference requires authentication; keyless private endpoints remain allowed by the registry contract. |

All direct and transitive locked library versions were checked against official PyPI version records on 11 November 2026; the complete results are in the Part B report. The new Gateway dependency is `confluent-kafka==2.16.1`, for confirmed audit delivery. No provider SDK is added. Tests use fake providers and Kafka; live checks make paid calls only when Claude runs the merged stage check while Aziz watches.

## Images and operating errors

The image keeps Python 3.14.10 and uv 0.13.7, running as 10001 with a read-only root and writable memory `/tmp`. Requests are 100m CPU / 128Mi; limits 1 CPU / 512Mi. The deployment has its existing migrate init container and one API replica. Setup preserves existing credentials, atomically writes mode-600 test settings outside the repository, waits up to 120 seconds for KafkaUser readiness and its Secret, and refuses a changed Kafka password.

| Message | Action |
|---|---|
| `usage: install/...` / invalid image tag | Follow the Quick Guide; deployment needs one 12-character hexadecimal image tag. |
| Invalid deployment value / missing tool | Ask the maintainer to correct deployment settings or finish server setup. |
| Platform namespace missing / PostgreSQL not Ready / database resources not ready | Complete platform/database setup; inspect status, then rerun setup. |
| Existing credentials unexpected / database password format unexpected / invalid ClusterIP | Have the maintainer inspect the named resource privately; never print credentials. |
| Cannot read client secret / client secret missing or changed | Inspect Keycloak readiness and the configured client privately before replacing the application copy. |
| `STOP: KafkaUser model-gateway not ready; re-run 30` | Finish the platform apply and rerun setup after the KafkaUser is Ready. |
| Kafka password changed | Have the maintainer reconcile the existing application Secret privately. |
| Database setup failed | Inspect PostgreSQL readiness and rerun setup. |
| Image not built / not public | Wait for a green workflow and make the named GitHub package Public. |
| Registry unreachable / check failed / invalid token | Check registry availability and retry. |
| Required application secret missing | Run setup. |
| New revision not Ready / migrations not verified / deployment failed | Inspect pod status and migration logs, then rerun deployment. |
| HTTP 400 | Use the documented input; chat requires a positive tier; correlation headers must be UUIDs. |
| HTTP 401 / 403 | Use a valid service token with the Gateway audience and permitted caller. |
| HTTP 404 `no_model` | Configure a supported active entry for the requested purpose/tier. |
| HTTP 429 `rate_limited` | Wait for the minute window or adjust the configured limit. |
| HTTP 503 `budget_exceeded` | Wait until the next UTC day or ask an admin to adjust the budget. |
| HTTP 503 `registry_unavailable` / `unavailable` | Inspect the Control Centre, database and provider connectivity, then retry. |

For pinned Control Centre tests only, 503 may include provider status and a scrubbed diagnostic (at most 300 characters, read from at most 4 KiB). These diagnostics are never logged. After a reboot, Kubernetes restarts the service; allow five minutes and follow the status and merged stage-check steps. Builders do not deploy, start servers or change cluster resources.
