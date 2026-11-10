# QUICK GUIDE

1. **Prepare the encryption key before the new Control Centre.** Claude runs this in the harness terminal, in the plain shell, while Aziz watches. No password is needed. This creates the encryption Secret once. Good result: `DONE`. An existing Secret is retained and is never overwritten.

   ```bash
   cd ~/projects/worktrees/stage-2
   install/63-control-centre-keys.sh
   ```

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

6. **Give access to a tier.** Do this in the same browser screen. In **Who may use this tier**, turn **Everyone** on or enter the user's ID and choose **Add person**. The user can copy their ID from the Workspace's About me line. Remove individual grants with **Remove access**. A tier with grants and no model stays visible as **No model yet**. The reserved installation-check tier 99 is hidden from these tier rows. Good result: the grant stays after reloading.

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
| `This console is for administrators.` | Sign out and use an account with realm role `ooh-admin`. |

Lost encryption Secret: saved provider keys cannot be recovered; after a replacement Secret is created with 63, retype each provider key in the console. Never commit or paste the Secret into chat. The Control Centre README describes an optional private backup.
