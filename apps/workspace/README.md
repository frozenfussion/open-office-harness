# QUICK GUIDE

1. **Install and check the app.** Type this in your harness terminal, plain shell
   (Codex may run these checks). No password. This installs the exact lock file,
   builds the app with the bundled design system and runs the tests once.
   Good result: build finishes and all tests pass.

   ```bash
   cd ~/projects/worktrees/stage-2-part-c/apps/workspace
   npm ci
   npx ng build
   npx ng test --watch=false
   ```

2. **Deploy the merged image.** Type this in your harness terminal, Shell tile,
   plain shell. Claude runs this while Aziz watches. No password. Replace
   `MERGED_IMAGE_TAG` with the merged commit's first 12 characters; the Workspace
   workflow must be green and its package Public first. This updates settings,
   replaces the placeholder and waits for the current image to be Ready.
   Good result: `Running image: ...`, then `DONE`.

   ```bash
   cd ~/projects/worktrees/stage-2
   install/68-workspace-deploy.sh MERGED_IMAGE_TAG
   ```

   Follow the [root stage order](../../README.md). After acceptance, use
   `cd ~/projects/open-office-harness` for deployment and everyday work.

3. **Use chat.** Open <https://harness.faysalaziz.com>. Click **Sign in with
   company account**, then sign in on Keycloak with your account password.
   Choose a **Chat model**, type a question and press Enter (Shift+Enter adds a line).
   The picker shows the tier's main model title followed by `- Tier N`, or just
   `Tier N` if no title is available. Only your allowed tiers appear.
   When the chosen model offers a **Thinking** switch, click it to turn thinking
   on or off. Your browser remembers the choice for each tier. A backup model
   might not support turning thinking off; the answer's meta line says so.
   Choose **Request another model…** at the end of the picker to ask for access.
   Pick a model, optionally give a reason (up to 300 characters), then click
   **Send request**. Pending models show **Requested**. A rejected model shows
   **Not approved** and can be requested again seven days after the last answer.
   The API enforces the wait and shows a plain notice if it refuses.

   The answer
   appears while it streams. Assistant replies support Markdown headings,
   lists, tables, links, code blocks and LaTeX maths. Your own messages stay
   plain text. Each message shows its date and time in your browser's time zone.
   **Copy** copies the original message, including Markdown and maths delimiters;
   **Copied** appears for two seconds. Code blocks have their own **Copy code**
   button. The line beneath the answer shows tier, model title and token counts. Pick a recent conversation to reopen it;
   reloading keeps the selected conversation. After the first completed answer,
   its AI title updates the heading and recent list when available. You can send
   again as soon as the answer finishes; title generation may take another
   20 seconds. If it fails, the first words of your question remain the title. **New chat** starts another one.
   Under your name, find **About me · Your user ID** and click **Copy user ID**
   to give an admin your ID. **Sign out** ends the Keycloak session.

   Newcomers use **Need access? Request access** on Keycloak's login page after
   the sign-in button. Enter names, work email, organisation, an optional reason
   and a chosen password twice. Pending, rejected and closed requests show only
   their message and Sign out. An approved request opens chat. Refresh after the
   admin approves. If the access service fails, a red notice appears. See the
   [root guide](../../README.md#request-access-and-approvals) for approval,
   registration controls and password resets.

4. **Read status and the running image.** Type this in your harness terminal,
   Shell tile, plain shell. No password. This shows the running app; good result
   is `1/1` Ready and the intended image tag.

   ```bash
   cd ~/projects/worktrees/stage-2
   kubectl -n ooh-apps get deployment workspace
   kubectl -n ooh-apps get deployment workspace -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
   ```

5. **Read logs.** Type this in your harness terminal, Shell tile, plain shell.
   No password. This shows recent HTTP status lines as JSON, with no URLs,
   tokens or chat text.

   ```bash
   cd ~/projects/worktrees/stage-2
   kubectl -n ooh-apps logs deployment/workspace --tail=50
   ```

6. **Restart.** Type this in your harness terminal, Shell tile, plain shell.
   Claude runs this while Aziz watches. No password. This restarts only
   Workspace; good result: `successfully rolled out`.

   ```bash
   cd ~/projects/worktrees/stage-2
   kubectl -n ooh-apps rollout restart deployment/workspace
   kubectl -n ooh-apps rollout status deployment/workspace --timeout=300s
   ```

7. **Stop the app.** Type this in your harness terminal, Shell tile, plain shell.
   Claude runs this while Aziz watches. No password. This stops only Workspace;
   conversations stay in the Harness database. Good result: `scaled`.

   ```bash
   cd ~/projects/worktrees/stage-2
   kubectl -n ooh-apps scale deployment/workspace --replicas=0
   ```

8. **Start the app.** Type this in your harness terminal, Shell tile, plain shell.
   Claude runs this while Aziz watches. No password. This starts Workspace;
   good result: `successfully rolled out`.

   ```bash
   cd ~/projects/worktrees/stage-2
   kubectl -n ooh-apps scale deployment/workspace --replicas=1
   kubectl -n ooh-apps rollout status deployment/workspace --timeout=300s
   ```

9. **After a reboot, check the stage.** Wait five minutes. Type this in your
   harness terminal, Shell tile, plain shell. Claude runs it while Aziz watches.
   No password. This checks the platform, Control Centre and chat connections.
   The Control Centre check asks for browser admin sign-in. Good result:
   every check prints `PASS`, each script ends with `DONE`.
   **Each run of 70 makes one short paid call per entry with a key, plus one
   streamed paid call per connection type in use and one pinned paid call as
   the Control Centre.** It tests chat tiers 1–20.

   ```bash
   cd ~/projects/worktrees/stage-2
   install/40-check-platform.sh
   install/62-check-control-centre.sh
   install/70-check-stage-2.sh
   ```

10. **If a script stops, use the table below.** Fix the reason before repeating
    the same command. Send only the STOP/FAIL line, never credentials or raw logs.

| Message contains | What to do |
|---|---|
| `missing tool` | Finish server setup; no system installs from Codex. |
| `invalid deployment value` | Correct the named value in `deploy/values/do.env`. |
| `usage:` | Use the script's command above; 68 takes one optional image tag, 70 takes no arguments. |
| `image tag must be` | Supply exactly the image commit's first 12 lowercase hexadecimal characters. |
| `image not built yet` | Wait for a green Workspace workflow or run it on demand for that commit. |
| `image not found or not public` | Check the workflow and make the `ooh-workspace` package Public on GitHub. |
| `registry is unreachable`, `registry check failed`, `invalid token` from the registry | Check ghcr.io connectivity and retry. |
| `new Workspace revision is not Ready`, `current revision could not be verified`, `Workspace deployment failed` | Check pod events, image visibility and config mount; redeploy the intended tag. |
| `local port 18080 is busy`, `local port 18081 is busy` | Stop the old port-forward with the command printed in the STOP line, then rerun 70. Type that command in the harness terminal, Shell tile, plain shell; the folder does not matter and no password is needed. It stops only the old forwarding process. |
| `port-forward ... could not start` | Check that Gateway and Control Centre Services and pods are Ready and the port is free. |
| `could not create private Keycloak CLI settings directory`, `Keycloak CLI login failed` | Check Keycloak readiness and bootstrap access privately. |
| `client secret unavailable`, `service token`, `invalid service token` | Check the existing Keycloak client, secret and audience mappers privately; run 35 after merging. |
| `no chat entry with a saved key` | Add an active chat model with a key in tiers 1–20 in the Admin Console. |
| `could not read ... logs` | Check pods and access to their logs; rerun once Ready. |
| `cannot continue after`, `Stage 2 check could not continue`, `Stage 2 checks failed` | Fix the preceding FAIL line or tool error before repeating. |
| `FAIL ... page`, `FAIL ... settings` | Check the app image, `config.json`, ingress and trusted certificate. |
| `FAIL Harness refuses` | Check Harness authentication and the token audience. Anonymous and wrong-audience calls must be 401. |
| `FAIL Gateway has no public ingress` | Have Claude remove the Gateway ingress before using keys. |
| `FAIL Gateway refuses` | Check caller validation; only the Harness service account may call the Gateway. |
| `FAIL Gateway reports no model` | Keep tier 98 empty and check internal registry access. |
| `FAIL read chat tier` | Check Control Centre internal port 8081, Gateway token and registry response. |
| `over its daily budget today` | Wait for the next UTC day or have an admin review the entry's daily budget. |
| `FAIL ... non-streamed answer` | Check connection type, endpoint, model ID, saved key, prices and time limit privately. |
| `FAIL ... streamed answer` | Check provider stream settings and buffering. The check requires at least two text deltas before completion. |
| `FAIL one usage row` | Check Gateway usage writes, app role and its password Secret; no manual table changes. |
| `FAIL key absent from logs` | Inspect privately. If a key leaked, rotate it and fix logging before retrying. |
| `FAIL Harness cannot read`, `FAIL key route is not public` | Fix Control Centre caller restrictions and public/internal port separation. |
| Amber chat notice | Follow the API's message; an admin may need to grant a tier. |
| Red chat notice or `Workspace could not start` | Retry or ask an admin to check API readiness, settings and sign-in configuration. |
| `sign-out redirect is not enabled` from 35 | Check the existing public client's logout attribute and repeat realm sync. |

The SSE parser handles UTF-8 byte boundaries, split lines and CRLF, using fetch
for POST streams. User messages use plain-text interpolation. Assistant Markdown
is parsed with marked, with raw HTML escaped as text and images suppressed.
DOMPurify sanitizes it with the row 22 forbidden-tag list. Only HTTP, HTTPS and
mailto links remain, opening with `target="_blank" rel="noopener noreferrer"`.
Closed maths delimiters (`$...$`, `$$...$$`, `\(...\)`, `\[...\]`) become
KaTeX output with `throwOnError: false` and `trust: false`, then a separate
DOMPurify pass admits KaTeX's generated HTML, MathML and SVG. Unfinished maths
stays literal text; code never gets maths parsing. Nothing bypasses sanitization.
Streaming rendering runs at most once per 100 ms, with an immediate final pass.
The renderer loads on demand; no rendering code or prompt text is logged.
KaTeX CSS and all fonts are local build assets, with no CDN. Its MIT licence is
copied beside the other font licences at `/design-system/licenses/MIT-katex.txt`.
Timestamps use stored `created_at` for history and browser send/completion times
for new messages. OIDC uses authorization code + PKCE S256, refresh tokens and the library's default
session storage. `/config.json` supplies all deployment addresses. The static
server logs only its service name and status code. Nginx error diagnostics are
suppressed to avoid recording callback URLs; use pod events for startup failures.

The build copies the unchanged design system through `public/design-system`, a
relative symlink to `../../design-system`. Run builds from the app folder;
Docker builds use the repository root as context so the same copy is available.
Font files and OFL licences ship in the image. Node `26.13.0-bookworm-slim` builds
it; nginx `1.28.0-alpine` runs as user 101 with a read-only root and writable
`/tmp` and `/var/cache/nginx` volumes. Only the runtime settings file is mounted.

The stage check uses fixed localhost ports 18080/18081, cleans up its own
port-forward processes and private Keycloak CLI directory on exit, and removes
its temporary SQL check pod. Usage rows stay append-only. Client credentials,
access tokens, decrypted keys and inspected service logs remain in shell variables;
credentials reach curl via standard input and the SQL password uses a Secret
reference in the pod environment. Tier 98 is reserved for the no-model check;
tier 99 is reserved for the earlier Control Centre check.

The sign-in setup follows the library's [configuration](https://www.angular-auth-oidc-client.com/docs/documentation/configuration)
and [session storage](https://www.angular-auth-oidc-client.com/docs/documentation/custom-storage)
documentation. Tests use the [Angular CLI unit-test builder](https://angular.dev/guide/testing)
with its default Vitest runner and jsdom.

Row 17 dependencies, checked on npm on 10 Nov 2026: marked **18.2.0** (Markdown),
DOMPurify **3.4.17** (HTML sanitization), KaTeX **0.19.1** (maths, with bundled
TypeScript declarations). Exact versions and transitive resolutions are locked.
The implementation follows the [marked extension API](https://marked.js.org/using_pro),
[DOMPurify sanitizer API](https://github.com/cure53/DOMPurify) and
[KaTeX options](https://katex.org/docs/options).

Thinking-off settings are configured on the model entry in the Admin Console.
Use the shape supported by that connection, with your configured model ID;
there are no provider/model addresses or names built into the Workspace:

| Connection type | Example settings when thinking is off |
|---|---|
| `openai_chat_completions` | For a service supporting the field: `{"thinking":{"type":"disabled"}}` or `{"reasoning_effort":"low"}` |
| `openai_responses` | `{"reasoning":{"effort":"low"}}` |
| `anthropic_messages` | Leave empty when the configured model has no off switch. |

The switch describes the tier's main entry; the meta line identifies the actual
answering model. The Gateway reports `thinking_applied` for the live answer;
this support notice is not saved in conversation history. Browser storage holds
only each tier's on/off preference, never a prompt, reason or token.

The reply-language system message is configured by Part B's `HA_SYSTEM_PROMPT`
in `deploy/apps/harness-api/configmap.yaml`. To change it, edit that file and
follow the Harness API deployment step in the [root guide](../../README.md),
which runs `install/67-harness-api-deploy.sh`. A live cluster edit is
overwritten by the next deploy. The title call uses its own system message.
Model requests go only through the same-host Harness API with the signed-in
user's identity; no user ID is sent from this form. The Control Centre decides
approval, eligibility, the seven-day rejection wait and the 20-pending limit.
