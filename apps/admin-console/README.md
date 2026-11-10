# QUICK GUIDE

1. **Prepare the encryption key before the new Control Centre.** Claude runs this in the harness terminal, in the plain shell, while Aziz watches. No password is needed. This creates the encryption Secret once. Good result: `DONE`. An existing Secret is retained and is never overwritten.

   ```bash
   cd ~/projects/worktrees/stage-2
   install/63-control-centre-keys.sh
   ```

**Enable connection tests.** Claude runs this in the harness terminal, in the plain shell, while Aziz watches. No password is needed. First follow the root README to sync the new realm audience mapper with 35. This copies the Control Centre's service credential privately from Keycloak; it retains a matching existing Secret and refuses to overwrite a changed one. Good result: `DONE`.

```bash
cd ~/projects/worktrees/stage-2
install/71-control-centre-oidc.sh
```

For the new Test button, the deployment order is realm sync → 71 → the new Gateway image with 65 → the new Control Centre image with 61 → the new console image with 69 → check 70. The Control Centre still starts without the optional service Secret; testing then reports “the Control Centre has no service credentials.”

2. **Deploy the Control Centre.** Claude runs this in the harness terminal, in the plain shell. No password is needed. The folder is the merged Stage 2 worktree. This uses the first 12 characters of its commit; the image workflow for that commit must be green. Good result: the new revision is Ready and `DONE`.

   ```bash
   cd ~/projects/worktrees/stage-2
   install/61-control-centre-deploy.sh
   ```

3. **Make the console image public once.** Do this in GitHub on your PC, in the browser. The folder does not matter and no shell command is needed. Claude opens `https://github.com/users/frozenfussion/packages/container/ooh-admin-console/settings`; Aziz chooses **Change visibility → Public** after the first green image workflow. Good result: anonymous image pulls work.

4. **Deploy or start the console.** Claude runs this in the harness terminal, in the plain shell. No password is needed. This deploys the image for the merged commit, waits for its new revision, and removes the old console and Control Centre placeholder ConfigMaps. Good result: `Running image: ...` and `DONE`.

   ```bash
   cd ~/projects/worktrees/stage-2
   install/69-admin-console-deploy.sh
   ```

   The full stage order, other service deployments and realm synchronization are in the root README. After acceptance, use `cd ~/projects/open-office-harness` for operational commands.

5. **Sign in and add a model.** Do this in your PC browser at `https://admin.faysalaziz.com`. Choose **Sign in with company account**; enter your account password only on Keycloak's page. An administrator sees **Models & tiers**. Choose **Add model**. Enter the name, purpose, chat tier, main or backup, location, connection type, endpoint, model ID, priority, rate, budget, prices and timeout. Extra request settings must be a JSON object, such as `{}`. Choose **Save model**. Good result: the model appears in its purpose/tier card and table. Cost today is `—` in this stage.

   Connection examples (replace `<model-id>` with your provider's model ID; no model is compiled into the app):

   | Connection type | Example endpoint | Model ID |
   |---|---|---|
   | OpenAI Responses | `https://api.openai.com/v1` | `<model-id>` |
   | Anthropic Messages | `https://api.anthropic.com` | `<model-id>` |
   | OpenAI-compatible | `https://api.deepseek.com` | `<model-id>` |
   | Anthropic Messages | `https://api.deepseek.com/anthropic` | `<model-id>` |
   | OpenAI-compatible, on-prem | `http://<host>:8000/v1` | `<model-id>` |

   These are help examples, never defaults or routing rules. The administrator chooses every address and model. `temperature`, `top_p` and `top_k` in extra request settings may be refused by newer Anthropic versions. Priority means “Order within the tier, lowest first”; the Gateway tries main entries before backups, then priority, then creation time. Budget `0` means no limit.

   Type the provider key once. It is stored encrypted and never filled back into the form. A blank field keeps the saved key; **Remove saved key** removes it. Changing the endpoint or connection type removes it unless a replacement is typed in the same save. **Switch off** asks for confirmation and marks the entry removed without deleting its row.

**Test a saved model.** Do this in the Admin Console browser screen. Each model row has **Test** in Actions. Save a key first to enable it. One click makes one short paid call to that entry only; it counts against its daily budget and rate limit. The button says **Testing…** until the result appears beneath the row. Success shows elapsed seconds, the first 80 reply characters, token counts and USD cost. A failure shows a plain reason, the provider status and its short message when available. The result stays until the next test or page reload. Provider messages are displayed as text. Tests wait at most the model's time limit plus 15 seconds in the browser; no provider key is returned.

6. **Give access to a tier.** Do this in the same browser screen. In **Who may use this tier**, turn **Everyone** on or enter the user's ID and choose **Add person**. The user can copy their ID from the Workspace's About me line. Remove individual grants with **Remove access**. A tier with grants and no model stays visible as **No model yet**. The reserved installation-check tier 99 is hidden from these tier rows. Good result: the grant stays after reloading.

**Review requests for access.** Do this in your PC browser in the Admin Console. Open **Access requests**; the badge shows waiting requests and disappears at zero. Waiting is shown first. Each email is labelled **not verified**. Choose a chat tier, then **Approve**; no tier is selected for you. **Reject** refuses a waiting request. Use the Rejected filter to approve one later. Use the Approved filter and **Revoke** to stop access; this blocks Everyone too. The existing grants remain stored and are usable again only if access is approved.

Adding a person by user ID under Models & tiers also approves their access, including a previously rejected person. It does not look up Keycloak. Repeating an existing user grant reuses it without adding a second grant. The approval tier list uses active model/grant tiers and hides reserved tier 99.

**How a newcomer requests access.** Do this in the Workspace browser. Choose **Sign in with company account**, then Keycloak's **Request access** link. The password is entered only in Keycloak. The Workspace shows a waiting message until an admin approves the request. A non-admin signing in to this console gets a link to the Workspace, because only the Workspace creates requests. Existing users known to the Control Centre before the migration are approved automatically. Users who previously had only Everyone and were not known must request access once.

At most 100 requests may wait. New requests beyond that return closed without creating a row. If spam appears, Claude can turn registration off using the root README's instructions for `install/35-realm-sync.sh --registration off`. No email verification or password-reset mail is sent.

7. **Check the running image and status.** Type this in your harness terminal, in the plain shell. No password is needed. The folder does not matter. This shows image names and readiness; the console should have one Ready replica.

   ```bash
   kubectl -n ooh-apps get deployment admin-console control-centre -o wide
   ```

8. **Read console logs.** Type this in your harness terminal, in the plain shell. No password is needed. The folder does not matter. This shows recent nginx errors; successful requests are not logged.

   ```bash
   kubectl -n ooh-apps logs deployment/admin-console --since=10m
   ```

9. **Restart the console.** Claude runs this in the harness terminal, in the plain shell, while Aziz watches. No password is needed. The folder does not matter. This replaces the pod using the same image; status should return to Ready.

   ```bash
   kubectl -n ooh-apps rollout restart deployment/admin-console
   ```

10. **Stop the console.** Claude runs this in the harness terminal, in the plain shell. No password is needed. The folder does not matter. This stops its pod without removing configuration. To start it again, rerun step 4, which restores one replica.

    ```bash
    kubectl -n ooh-apps scale deployment/admin-console --replicas=0
    ```

11. **Build and test locally.** Type this in your harness terminal, in the plain shell. No password is needed. This installs the exact lock file, copies the shared design assets, builds and runs tests without a watcher. Good result: build completes and every test passes.

    ```bash
    cd ~/projects/worktrees/stage-2-part-d/apps/admin-console
    npm ci
    npx ng build
    npx ng test --watch=false
    ```

12. **After a reboot.** Kubernetes starts the console again by itself; allow five minutes. Claude runs the platform and stage checks from the root README in the shell tile. Good result: checks say `DONE`, both apps open, and sign-in works. No manual service start is needed.

# Admin Console

Standalone Angular 22, strict TypeScript and templates, authorization code with PKCE S256, refresh tokens and the OIDC library's default session storage. Runtime `/config.json` supplies issuer, client ID and `/api`; domains are not compiled in. Browser calls stay on the console's origin. API authorization is always enforced by the Control Centre; hiding the console from a non-admin is an additional UI guard.

The build copies `apps/design-system` into `public/ds` using Node's built-in filesystem API. Copied assets are ignored by git and are never edited. Fonts and their OFL licences are shipped intact. The Docker build context is the repository root; it copies only the app source/config and design files. Build image: `node:26.13.0-bookworm-slim`; run image: `nginxinc/nginx-unprivileged:1.28.0-alpine`. Both exact tags were checked against the registry. The runtime uses user 101, a read-only root filesystem, writable `/tmp` and nginx cache volumes, no access logging, and no embedded credentials.

# STOP messages and recovery

| Message or failure | What to do |
|---|---|
| `usage: ...`, invalid deployment value or invalid tag | Use the documented command; correct `deploy/values/do.env`; tags contain exactly 12 lowercase hexadecimal characters. |
| `missing tool ...` | Finish the server setup; builders do not install system tools. |
| `run install/63-control-centre-keys.sh` | Run step 1 before deploying the new Control Centre. |
| `encryption Secret setup failed` | Check cluster access, namespace and permissions, then rerun 63. Existing Secrets are never overwritten. |
| `image not built yet` | Wait for a green workflow for the exact commit, then rerun deployment. |
| `image not found or not public` | Check the green workflow and perform step 3. |
| `registry is unreachable`, `registry check failed`, invalid registry token | Check registry availability and retry. |
| `new ... revision is not Ready`, `current revision ... could not be verified`, deployment failed | Inspect pod status and logs; fix the migration, missing settings or image visibility, then rerun the script. |
| `local port 18081 is busy` from 62 | Stop the old forward as the message instructs, then rerun the check. |
| `internal port-forward failed` or `not ready` | Check Control Centre readiness and its internal Service port, then retry. |
| `FAIL ...` or another `STOP:` from 62 | Follow the Control Centre README and the root Stage 1 check guidance; do not treat the check as passed. |
| Console could not start or sign-in failed | Reload; check `/config.json`, the issuer, realm sync and the public app route. |
| Extra request settings rejected | Enter a JSON object, not an array, number, string or null. |
| Control Centre service credentials missing | Claude runs 71, then deploys or restarts the Control Centre as described in its README. |
| `the Control Centre client secret changed` from 71 | Ask the maintainer to inspect the changed credential privately; 71 never overwrites it. |
| Connection test cannot sign in to the Gateway | Check the realm audience mapper, matching service Secret and new Gateway deployment. |
| Connection test says key refused / provider account has no credit | Replace the saved provider key or restore credit with the provider, then test again. |
| Connection test says rate limited / over daily budget | Wait for the limit window or UTC day, or adjust the entry's configured limits. |
| `This console is for administrators.` | Sign out and use an account with realm role `ooh-admin`. |

Lost encryption Secret: saved provider keys cannot be recovered; after a replacement Secret is created with 63, retype each provider key in the console. Never commit or paste the Secret into chat. The Control Centre README describes an optional private backup.


# Request access deployment

After the combined section 17 changes are reviewed and merged, Claude runs the
non-sudo scripts in the shell tile in this order: 61 → 67 → 35 → 68 → 69 → 62 →
70. The Control Centre admission rule and Harness observe call must exist before
registration is opened. The root Quick Guide supplies the exact commands.

If check 62 says the reserved check user is not pending, requests may be closed
at the waiting cap or that reserved identity may have been approved manually.
Review waiting requests and the check identity's status before retrying. Check
62 reuses `stage-check-access`, verifies the Everyone gate on tier 99, and removes
the temporary Everyone grant. Reserved check identities are hidden from the
admin request list and count.

# Thinking settings and model requests (rows 19–22)

In **Add model** or **Edit model**, **Settings when thinking is off (JSON object)**
is optional. Leave it blank if the model has no off switch. A JSON object,
including `{}`, enables the switch for that entry; other JSON values are refused.
The model ID remains the placeholder `<model-id>` until an administrator supplies
it. Use settings supported by that model and connection type:

| Connection type | Thinking-off setting shape |
|---|---|
| `openai_chat_completions` | `{"thinking":{"type":"disabled"}}` or `{"reasoning_effort":"low"}` when supported |
| `openai_responses` | `{"reasoning":{"effort":"low"}}` when supported |
| `anthropic_messages` | Leave blank when the model has no off switch |

The Workspace picker name and switch come from the active main entry. The
answer's metadata identifies the real answering model; backup support may differ.
The console's **Test** button still sends only the fixed connection test fields;
it does not send a thinking choice.

**Access requests** also contains **Model requests**, with the same Waiting,
Approved and Rejected filter. Each row shows the person's name and unverified
email, requested model title and tier, optional reason, UTC request time and
**Approve**/**Reject** buttons for waiting requests. All text is displayed as text.
The badge adds both waiting counts and hides at zero. Both lists read every page.
Approving adds the user's tier grant without duplicates. If access was revoked,
approve access first, then decide the model request. A rejected model request can
be sent again after seven days; a person can have at most 20 waiting model requests.
Reserved installation-check users stay hidden. No request reason is logged or
audited.

The build recopies the shared design system, including the padded select and
inset arrow. No local select override replaces that shared rule.
