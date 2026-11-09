# QUICK GUIDE

## Stage 1 — Control Centre

Only Aziz runs the deployment and live-check scripts. Use the Shell tile, plain
shell, for every command below. None of these scripts asks for a password.
Everyday work uses `~/projects/open-office-harness` on `main`. Until Stage 1 is
accepted, only first-deploy steps 4–6 use the merged `stage-1` worktree. Pushing
that merged branch builds the image with its exact 12-character commit tag.
On a fresh server, finish the Stage 0 setup below first; the apply/check order is
**30 → 59 → 60 → 61 → 40 → 62**.

1. **Install the .NET SDK once.** Type this in your harness terminal, Shell
   tile, plain shell. The folder does not matter. This installs the pinned SDK
   in your home folder and loads the permanent PATH settings in this shell.
   No password. Good result: `10.0.403`.

   ```bash
   if curl -fsSL https://dot.net/v1/dotnet-install.sh -o /tmp/dotnet-install.sh && bash /tmp/dotnet-install.sh --version 10.0.403 --install-dir "$HOME/.dotnet"; then
     mkdir -p "$HOME/.local/bin"
     ln -sf "$HOME/.dotnet/dotnet" "$HOME/.local/bin/dotnet"
     if ! grep -q DOTNET_ROOT "$HOME/.profile"; then
       printf '\nexport DOTNET_ROOT="$HOME/.dotnet"\nexport DOTNET_CLI_TELEMETRY_OPTOUT=1\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$HOME/.profile"
     fi
     . "$HOME/.profile"
     dotnet --version
   else
     echo "STOP: .NET install failed"
   fi
   ```

2. **Make the databases.** Type this in your harness terminal, Shell tile,
   plain shell. This creates the live and test databases, each with a separate
   owner and app role. No password. Good result: four roles and two databases
   meet their condition, private test settings are saved, then `DONE`.

   ```bash
   cd ~/projects/open-office-harness
   install/59-control-centre-databases.sh
   ```

   Passwords are generated, never displayed and kept on repeat runs. The file
   `~/.config/ooh/control-centre-test.env` has mode 600 and contains only test
   database connections. Never paste it into chat or commit it.

3. **Check the image build on GitHub.** Open the repository's Actions tab and
   select **Control Centre image**. A green tick means the image is ready.
   The tag is the first 12 characters of the merged `stage-1` commit.
   If a merge did not start a build, choose **Run workflow** for that branch.
   First time only, on GitHub: open package `ooh-control-centre` → **Package
   settings** → **Change visibility** → **Public**, if it is not already public.
   The deployment script checks the image without signing in.

4. **Copy application secrets.** Type this in your harness terminal, Shell
   tile, plain shell. This creates the two Kafka users and copies database and
   Kafka credentials into the apps namespace. No password. Good result:
   `Created` or `Already exists` for each application secret, then `DONE`.
   A repeat run never overwrites an existing secret. It compares the saved Kafka
   password with Strimzi and stops if they differ, without displaying either.

   ```bash
   cd ~/projects/worktrees/stage-1
   install/60-control-centre-secrets.sh
   ```

5. **Deploy the image.** Type this in your harness terminal, Shell tile, plain
   shell. Replace `MERGED_IMAGE_TAG` with the first 12 characters of the merged
   commit.
   This runs migrations as the database owner, then starts the app with its
   restricted role. No password. `Waiting for migrations` is normal; allow up
   to ten minutes. Good result: rollout succeeds, the old API placeholder is
   removed, the running image is printed, then `DONE`.

   ```bash
   cd ~/projects/worktrees/stage-1
   install/61-control-centre-deploy.sh MERGED_IMAGE_TAG
   ```

   The tag may be omitted when the workflow has built this worktree's current
   commit.

6. **Check the Control Centre.** Type this in your harness terminal, Shell
   tile, plain shell. This checks sign-in, rights, registries, approvals,
   outgoing Kafka events and database audit protection. No password in the
   terminal. When the script prints a browser link and code, open that link,
   enter the code and sign in as an administrator in your browser. Tokens are
   held only in shell variables and refreshed before each admin call.
   Good result: every check prints `PASS`, then `DONE`.

   ```bash
   cd ~/projects/worktrees/stage-1
   install/62-check-control-centre.sh
   ```

   Check data uses a new random user id on each run. Grants and model entries
   are removed by setting their removal date; the generated tier right and
   Slides registration remain. Approvals and audit records remain. Temporary
   Kafka check pods remove themselves. Before this run's writes, the check sets
   its reserved consumer group to the newest offsets on audit.events and
   approvals.decided; it never scans old topic history. Run only one copy of the
   check at a time. Slides must have an audit row from any run; a matching Kafka
   message is required only when this run created that row (HTTP 201).
   Pending approvals for action `stage.check` from interrupted runs are rejected
   through the API with note `stale stage check`; other actions are untouched.
   Database protection checks always roll
   back, including when a protection check unexpectedly succeeds.

7. **Everyday status and logs.** Type this in your harness terminal, Shell
   tile, plain shell. Use the main clone. This shows readiness and
   the exact running image. No password. Good result: `1/1` Ready and the
   intended image tag.

   ```bash
   cd ~/projects/open-office-harness
   kubectl -n ooh-apps get deployment control-centre
   kubectl -n ooh-apps get deployment control-centre -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
   ```

   Type this in your harness terminal, Shell tile, plain shell. Use the main
   clone. This shows the app's recent logs. No password. Do not paste
   private log content into chat.

   ```bash
   cd ~/projects/open-office-harness
   kubectl -n ooh-apps logs deployment/control-centre -c control-centre --tail=100
   ```

   Type this in your harness terminal, Shell tile, plain shell. Use the main
   clone. This shows the migration logs if startup failed. No password.

   ```bash
   cd ~/projects/open-office-harness
   kubectl -n ooh-apps logs deployment/control-centre -c migrate --tail=100
   ```

   Type this in your harness terminal, Shell tile, plain shell. Use the main
   clone. This restarts the Control Centre. No password. Good result:
   rollout succeeds; migrations run again and keep existing data.

   ```bash
   cd ~/projects/open-office-harness
   kubectl -n ooh-apps rollout restart deployment/control-centre
   kubectl -n ooh-apps rollout status deployment/control-centre --timeout=600s
   ```

   Type this in your harness terminal, Shell tile, plain shell. Use the main
   clone. This stops the app while keeping all data. No password.
   Good result: deployment scaled.

   ```bash
   cd ~/projects/open-office-harness
   kubectl -n ooh-apps scale deployment/control-centre --replicas=0
   ```

   Type this in your harness terminal, Shell tile, plain shell. Use the main
   clone. This starts the app again. No password. Good result: rollout
   succeeds.

   ```bash
   cd ~/projects/open-office-harness
   kubectl -n ooh-apps scale deployment/control-centre --replicas=1
   kubectl -n ooh-apps rollout status deployment/control-centre --timeout=600s
   ```

8. **After a reboot.** Kubernetes starts the app by itself if it was running
   before the reboot. Allow five minutes. Type this in your harness terminal,
   Shell tile, plain shell. No password. This checks the platform, then the
   Control Centre, including browser sign-in again. Good result: both scripts
   finish with `DONE` and no `FAIL` lines.

   ```bash
   cd ~/projects/open-office-harness
   install/40-check-platform.sh
   install/62-check-control-centre.sh
   ```

9. **Builder checks (after acceptance).** Type this in your harness terminal,
   plain shell. This formats, builds and tests the code, including the test
   database. No password. Good result: all checks pass. Part A also documents
   local migrations and its pinned EF tool in `services/control-centre/README.md`.

   ```bash
   cd ~/projects/open-office-harness/services/control-centre
   dotnet format --verify-no-changes
   dotnet build -warnaserror
   dotnet test
   ```

10. **When a Stage 1 script stops.** A `STOP:` or `FAIL` line names the failed
    step. Fix that problem, then repeat the same script. Never print or replace
    credentials to diagnose a failure.

    | Message | What to do |
    |---|---|
    | Missing tool | Finish server setup; for .NET use step 1 above. |
    | Invalid deployment value | Correct DOMAIN, PLATFORM_NAMESPACE and APPS_NAMESPACE in deploy/values/do.env. |
    | Usage or invalid image tag | Use the command above with exactly the 12-character image tag. |
    | Namespace missing | Finish platform setup and application before database setup. |
    | PostgreSQL not Ready, missing ClusterIP, database resources not ready | Inspect platform pods and Database/DatabaseRole status; repeat database setup once PostgreSQL is healthy. |
    | Unexpected credentials or password format | Have the maintainer inspect the named Secret privately; never paste it into chat or replace it. |
    | Database setup failed | Check PostgreSQL readiness, fix the failing step and repeat 59. |
    | Live database not ready | Run 59 first. |
    | Kafka user not Ready or password missing | Inspect Strimzi and KafkaUser status, wait for Ready and repeat 60. |
    | Kafka password changed in Strimzi | Ask the maintainer before replacing control-centre-kafka; the script preserves the existing Secret. |
    | Secret setup failed or application secret missing | Check platform readiness and run 60 again. Existing secrets are kept. |
    | Image not built yet | Run the workflow for the code commit; wait for a green tick and make the package public. |
    | Image exists but is not public | Switch the ooh-control-centre package to Public on GitHub, as in step 3. |
    | Registry unreachable or registry check failed | Check ghcr.io availability and retry. |
    | Registry returned an invalid token | Retry; inspect ghcr.io availability if it continues. |
    | Unexpected admin certificate issuer | Inspect the existing admin Ingress; keep the certificate managed by that Ingress. |
    | Deployment, revision or migrations not Ready | Read migration and pod logs above. Check the public package and exact tag. Never edit an applied migration. |
    | Keycloak CLI login or client secret unavailable | Inspect Keycloak readiness and bootstrap access privately; the named existing client must exist. |
    | Device sign-in unavailable | Run `install/35-realm-sync.sh`, then repeat 62. This updates existing clients only. |
    | Device sign-in refused, expired, invalid timing or missing refresh token | Retry and sign in promptly as an administrator; inspect Keycloak client settings if it repeats. |
    | Account is not an administrator | Repeat the check and sign in with the ooh-admin account. |
    | Start Kafka check at newest offsets FAIL | Check Kafka access, ensure no other ooh-stage-check consumer is running and retry. |
    | Approval list is not an array, paging did not advance or invalid response id | Inspect the API contract and response handling before retrying. |
    | HTTP sign-in, audience or registry access FAIL | Check the expected HTTP status printed with the check and the realm audience mappers. |
    | Rights, model or skill FAIL | Check fixed rights rules, grants and the API contract; everyone grants may affect the empty-user check. |
    | Approval or Kafka event FAIL | Inspect Control Centre consumer/outbox logs, Kafka users and topics; repeat after the cause is fixed. |
    | Audit query or database protection FAIL | Stop testing and ask the maintainer to review migrations and database privileges; checks roll back without changing audit rows. |
    | Check could not continue | Fix the last FAIL or platform readiness problem, then repeat 62. |

## Stage 0 — Foundation

1. **What this is.** Open Office Harness is an open-source office AI platform.
   Stage 0 installs its foundation; the apps are placeholder pages. The Droplet
   runbook lives in the course's own private notes, outside this repository.

2. **Set up the server once.** Only Aziz runs setup and deployment commands.
   Type this in your harness terminal, in the `shell` tile (plain shell, not Codex).
   The folder doesn't matter for this command. This downloads the repository.
   No password is requested for this public clone.

   ```bash
   mkdir -p ~/projects/open-office-harness
   cd ~/projects/open-office-harness
   git clone https://github.com/frozenfussion/open-office-harness.git .
   ```

   Type this in your harness terminal, `shell` tile, plain shell. This enters the
   clone and installs server tools. It will ask for harness's sudo password.
   Good result: the setup script ends with `DONE`.

   ```bash
   cd ~/projects/open-office-harness
   sudo install/01-server-setup.sh
   ```

   Type this in your harness terminal, `shell` tile, plain shell. Use the repository folder shown below. This loads kubectl access in this terminal and signs Git into
   GitHub. Follow GitHub's browser sign-in instructions; no sudo password.

   ```bash
   cd ~/projects/open-office-harness
   export KUBECONFIG="$HOME/.kube/config"
   gh auth login
   gh auth setup-git
   ```

   Type this in your harness terminal, `shell` tile, plain shell. This enters
   the repository and creates private local settings **only if missing**.
   No password. Good result: the file opens; fill in `LETSENCRYPT_EMAIL`, then save and exit the editor.
   The firewall must allow incoming TCP 22, 80 and 443; Aziz sets it in
   DigitalOcean. Files use a 20Gi volume on the Droplet disk.

   ```bash
   cd ~/projects/open-office-harness
   mkdir -p ~/.config/ooh
   (umask 077; test -e ~/.config/ooh/do.env || cp install/ooh.env.example ~/.config/ooh/do.env)
   nano ~/.config/ooh/do.env
   ```

3. **Check the server.** Type this in your harness terminal, `shell` tile, plain
   shell. This checks the node, local settings, DNS, Traefik pod readiness and
   local HTTP/HTTPS responses. Any HTTP status (including 404) is good here;
   the local HTTPS check allows Traefik's initial untrusted certificate.
   No password. Good result: all `PASS` lines, then `DONE`.

   ```bash
   cd ~/projects/open-office-harness
   install/00-check-server.sh
   ```

4. **Install operators.** Type this in your harness terminal, `shell` tile, plain
   shell. This installs the pinned platform operators and waits for them.
   No password. Good result: deployments successfully rolled out, then `DONE`.

   ```bash
   cd ~/projects/open-office-harness
   install/10-platform-operators.sh
   ```

5. **Create secrets.** Type this in your harness terminal, `shell` tile, plain
   shell. This generates database and bootstrap passwords. It asks for no keys
   or passwords.
   Good result: each secret says `Created` or `Already exists`, then `DONE`.
   Secrets are never displayed or overwritten. Never paste them into Codex.

   ```bash
   cd ~/projects/open-office-harness
   install/20-platform-secrets.sh
   ```

6. **Apply the platform.** Type this in your harness terminal, `shell` tile, plain
   shell. This creates the foundation and placeholder pages. No password.
   Allow several minutes. `Waiting for Kafka` and `Waiting for certificate`
   messages are normal. Staging certificates prove Let's Encrypt can reach the
   server from outside; only then does the script request production certificates.
   Good result: resources become Ready, then `DONE`. A repeat run preserves
   production issuers and existing data. It also synchronizes client audience
   mappers using `install/35-realm-sync.sh` and marks bound data volumes Retain.
   Kafka, PostgreSQL and files use `local-path`. A short-lived pod first mounts
   a fresh file claim so its PV can be marked Retain before the apply completes.

   ```bash
   cd ~/projects/open-office-harness
   install/30-platform-apply.sh
   ```

7. **Check the platform.** Type this in your harness terminal, `shell` tile, plain
   shell. This checks pods, trusted HTTPS, issuer, all eleven topics, Kafka rights,
   database access, file volume read/write and Retain policy on all three data volumes. No password. It creates temporary
   check pods and removes them. Small test files under `checks/` stay on the
   `ooh-files` volume in `ooh-apps`.
   Good result: every line says `PASS`, then `DONE`.

   ```bash
   cd ~/projects/open-office-harness
   install/40-check-platform.sh
   ```

8. **Create the first admin.** Type this in your harness terminal, `shell` tile,
   plain shell. This asks for username, email and password twice (password hidden).
   No sudo password. Good result: `First admin created`, then `DONE`.
   Open <https://auth.faysalaziz.com/realms/ooh/account>, sign in and change the
   password when asked. A repeat run leaves an existing administrator unchanged.

   ```bash
   cd ~/projects/open-office-harness
   install/50-first-admin.sh
   ```

9. **Everyday tasks.** Type this in your harness terminal, `shell` tile, plain
   shell. Use the repository folder shown below. This lists pods; no password.
   Good result: running pods show Ready; completed setup jobs may show Completed.

   ```bash
   cd ~/projects/open-office-harness
   kubectl get pods -A
   ```

   Type this in your harness terminal, `shell` tile, plain shell. Use the repository folder shown below. This reads Workspace logs; no password.

   ```bash
   cd ~/projects/open-office-harness
   kubectl -n ooh-apps logs deployment/workspace --tail=50
   ```

   Type this in your harness terminal, `shell` tile, plain shell. Use the repository folder shown below. This restarts Workspace and waits for it; no password.
   Good result: `successfully rolled out`.

   ```bash
   cd ~/projects/open-office-harness
   kubectl -n ooh-apps rollout restart deployment/workspace
   kubectl -n ooh-apps rollout status deployment/workspace --timeout=300s
   ```

   Type this in your harness terminal, `shell` tile, plain shell. Use the repository folder shown below. This stops the Workspace placeholder only; no password.
   Kafka, PostgreSQL and Keycloak remain running; do not scale them to stop apps.

   ```bash
   cd ~/projects/open-office-harness
   kubectl -n ooh-apps scale deployment/workspace --replicas=0
   ```

   Type this in your harness terminal, `shell` tile, plain shell. Use the repository folder shown below. This starts the Workspace placeholder; no password.
   Good result: `successfully rolled out`.

   ```bash
   cd ~/projects/open-office-harness
   kubectl -n ooh-apps scale deployment/workspace --replicas=1
   kubectl -n ooh-apps rollout status deployment/workspace --timeout=300s
   ```

   After a reboot, k3s starts the platform automatically. Wait five minutes,
   then repeat step 7. For the stage's reboot test, Aziz alone runs the following.
   Type this in your harness terminal, `shell` tile, plain shell. Use the repository folder shown below. This reboots harness; it will ask for harness's sudo password.

   ```bash
   cd ~/projects/open-office-harness
   sudo reboot
   ```

10. **Builder checks.** Type this in your harness terminal, `shell` tile, plain
    shell. This checks contracts (after Part A is merged), shell files and YAML.
    No password. Good result: tests pass, shell tools print no errors, YAML has
    zero errors. The apply script with `--check` only renders and validates YAML;
    it makes no cluster changes. Custom resource kinds are explicitly skipped;
    their actual admission and readiness checks happen during Aziz's deployment.

    ```bash
    cd ~/projects/open-office-harness
    uv run --project contracts/check pytest
    uv run --project contracts/check ruff check contracts/check
    uv run --project contracts/check ruff format --check contracts/check
    for script in install/*.sh; do bash -n "$script"; done
    shellcheck install/*.sh
    install/30-platform-apply.sh --check
    ```

11. **If a script stops.** Read the table below. Stop at the first failed step;
    send Codex the `STOP:` or `FAIL` line without secrets. Fix the reason, then
    run that same step again. Never loop certificate requests when rate limited.

| Message contains | What to do |
|---|---|
| `local settings missing` | Create the settings file in step 2. |
| `local setting ... is empty`, `contact email is invalid`, `unsupported characters` | Open the local settings file and fill in a valid email. |
| `missing tool` | Ask Aziz to finish server setup; Codex does not install system tools. |
| `k3s node is not Ready`, kubectl access error | Check server setup and kubectl access; wait for k3s after reboot. |
| `DNS lookup failed`, `does not resolve only to` | Correct the named A record to 143.198.221.2 or wait for DNS to spread. |
| `Traefik pod is missing or not Ready` | Inspect Traefik pods in kube-system and wait for them to become Ready. |
| `local Traefik request failed`, `no HTTP status from` | Inspect Traefik and ServiceLB. Local HTTP and HTTPS must return a status; 404 is normal before ingress routes exist. |
| `<url> not found` | The server returned HTTP 404 after retries. Send the URL to Codex; verify the same version on the vendor's release page. Do not substitute a new version. |
| `<url> download failed (HTTP ...; curl exit ...)` | Retries were exhausted. HTTP 504 or another server error can be temporary; wait and rerun the same script. HTTP 000 means no HTTP response; check connectivity and the curl error. |
| `platform namespace missing` | Run step 4 (operators) first, then repeat step 5. |
| `invalid deployment value`, `usage: install/30-platform-apply.sh` | Check deploy/values/do.env and use step 6, or `--check` for local validation. |
| `file claim binding failed` | Inspect the file claim, binding pod and local-path provisioner; fix scheduling or disk issues and repeat step 6. |
| `Keycloak rollout is not Ready on the current revision` | Inspect the Keycloak CR, StatefulSet and pod. Allow rollout to finish, then repeat step 6. Both apply and realm sync wait for a non-terminating Ready pod on the target revision. |
| `client ... is missing from realm ooh` | Inspect initial realm setup. Sync updates mappers only and will not create clients. |
| `mapper name conflicts`, `duplicate mapper names` | Inspect the named client before retrying; the sync stops rather than overwriting an unrelated mapper. |
| `Keycloak CLI login failed`, `Keycloak CLI ... failed`, `realm audience sync failed`, `realm client format changed`, `could not create private Keycloak CLI settings directory`, `audience verification failed` | Read the redacted CLI error or FOUND/EXPECTED audience names, check Keycloak readiness, bootstrap access and realm manifest format, then repeat step 6. |
| `required secret missing` | Run step 5 first. |
| `certificate pending for` | Check DNS and DigitalOcean inbound TCP 80/443; inspect cert-manager events and logs. Staging issuance is the real outside check. |
| `production certificate pending` | Inspect certificate events. If rate limited, wait for the stated limit window before retrying. |
| Keycloak crashes with `--optimized flag was used for first ever server start` | Stop the waiting apply script with Ctrl+C. The stock image requires `startOptimized: false`, which is set in the manifest. Re-run step 6 with the corrected manifest; existing resources and secrets are reused. |
| Keycloak keeps crashing on an old StatefulSet revision after the manifest fix | Follow the one-time Keycloak pod recovery below, then repeat step 6. |
| `step failed; see README` | Read the immediately preceding tool error. Check operator/pod events, connectivity, storage and memory; send the error to Codex. No changes are rolled back or deleted. |
| `admin request failed` | Check Keycloak readiness and bootstrap secret; re-run step 8. A partly created marked first-admin account gets its role completed without changing its password. |
| `username/email/password missing or passwords differ` | Repeat step 8 with nonempty username, valid email and matching passwords. |
| `username already exists` | Ask Aziz to inspect that account; the script will not overwrite an unrelated account. |
| `FAIL pods` | Check pending/crashing pods, memory, storage and operator logs. Completed jobs are excluded. |
| `FAIL production certificate`, `FAIL HTTPS` | Check ingress, deployment, DNS and certificate events; HTTPS must validate without bypassing TLS checks. |
| `FAIL OIDC issuer` | Check realm import, Keycloak hostname and `proxy.headers: xforwarded`. |
| `FAIL topic` | Re-run step 6; inspect the named KafkaTopic and Kafka readiness. |
| `FAIL Kafka smoke` | Inspect KafkaUser `ooh-smoke` and its ACLs. Only `ooh.smoke` is permitted; denial must specifically be a topic authorization error. |
| `FAIL PostgreSQL` | Inspect database/role status and the `keycloak-db` secret reference. Passwords must match; do not replace existing secrets blindly. |
| `FAIL PV retention` | Inspect the bound claim and PV. Step 6 must set the PV reclaim policy to Retain; the class stays local-path. |
| `FAIL storage` | Inspect PVC `ooh-files` in `ooh-apps`, the local-path provisioner, disk space and check pod volume permissions. The test file is retained. |
| `platform checks failed` | Fix every `FAIL` line above it, then repeat step 7. |

Type this in your harness terminal, `shell` tile, plain shell. Use `cd ~/projects/open-office-harness` as shown below. This shows platform events for troubleshooting; no password.

```bash
cd ~/projects/open-office-harness
kubectl -n ooh-platform get events --sort-by=.metadata.creationTimestamp
kubectl -n cert-manager get events --sort-by=.metadata.creationTimestamp
```

If Keycloak still crash-loops after a manifest fix, its StatefulSet can be waiting
for the broken old pod instead of replacing it. First stop the waiting apply
script with Ctrl+C in the shell tile.

Type this in your harness terminal, `shell` tile, plain shell. Use `cd ~/projects/open-office-harness` as shown below. This shows the StatefulSet's current and target revisions, plus the pod's
revision and container state. No password is requested.

```bash
cd ~/projects/open-office-harness
kubectl -n ooh-platform get statefulset ooh-keycloak -o 'jsonpath={.status.currentRevision}{" current\n"}{.status.updateRevision}{" target\n"}'
kubectl -n ooh-platform get pod ooh-keycloak-0 -o 'jsonpath={.metadata.labels.controller-revision-hash}{" pod revision\n"}{.status.containerStatuses[*].state}{"\n"}'
```

Only if the pod is crash-looping on an old revision that differs from the target,
use this one-time recovery. Type this in your harness terminal, `shell` tile,
plain shell. Use the repository folder shown below. This removes the broken pod once; the
StatefulSet creates its replacement using the updated configuration. No password
is requested. Then repeat step 6 and send the result to Codex.

```bash
cd ~/projects/open-office-harness
kubectl -n ooh-platform delete pod ooh-keycloak-0
```

## What is where

| Path | Contents |
|---|---|
| `deploy/platform/` | Namespaces, certificates, Kafka, PostgreSQL, Keycloak, file PVC and placeholder manifests |
| `deploy/platform/postgres/cluster.yaml` | Proven first-boot setup creates the keycloak database and owner with the database secret. |
| `deploy/platform/postgres/db-keycloak.yaml` | Database and managed-role resources maintain that same setup after bootstrap. Both definitions are intentional: initial creation and ongoing management. |
| `deploy/values/do.env` | Public deployment values; no credentials or personal contact data |
| `install/ooh.env.example` | Template for private local settings in `~/.config/ooh/do.env` |
| `install/00` through `install/50` scripts | Server check, operators, secrets, apply, realm sync, checks, first admin |
| `docs/specs/` | Stage spec and global rules |
| `contracts/` | Module agreements and contract checks (Part A) |

Secrets exist in Kubernetes only; interactive inputs are held in process memory.
Kafka check credentials exist briefly in a temporary pod's in-memory volume.
Files live on the Droplet disk in the `ooh-files` PVC (`ooh-apps`, 20Gi).
All three data volumes use the existing `local-path` StorageClass. The apply
script creates the file claim and briefly mounts it in a temporary pod if it
is not yet Bound, so its PV exists before retention is set. The short-lived pod writes `checks/stage0-<time>.txt`,
reads it back and leaves the file in place. It reuses the pinned PostgreSQL image
for its shell tools, adding no new image or storage server.
No application or database data is removed by these scripts. All persistent
volumes use the k3s local-path provisioner. The apply script patches the reclaim
policy of every bound Kafka, PostgreSQL and file PV to Retain without replacing
claims. The platform check verifies all three groups remain Bound on local-path
with Retain. No additional StorageClass is installed.
Apply and realm sync wait up to ten minutes for the current Keycloak CR and
StatefulSet rollout, including a Ready pod matching the target revision.
Keycloak realm import creates the initial realm. The realm-sync script then
requires every client to exist and looks up mappers by name. It creates missing
audience mappers, updates
changed audience mappers individually by ID and skips equal entries. Unwanted
audience mappers are removed, including Control Centre's self and Model Gateway
audiences. Verification reads both included client and custom audiences and
ignores harmless extra config defaults. Admin Console expects only
`ooh-control-centre`. Other mapper types, users and existing client credentials
are preserved. It uses Keycloak's own admin CLI inside
the pod using its operator-provided bootstrap environment variables. Credentials
expand only inside the pod; the realm-sync script never reads the Secret on the
Droplet or includes credential values in kubectl arguments. It uses a mode 600
config file under a writable `/tmp` emptyDir, removed on exit. Login errors have
exact credentials redacted inside the pod before output leaves it. CLI errors are shown with credentials and tokens
redacted; successful login output is suppressed.
Keycloak runs as a non-root user; its root filesystem remains writable because
the stock image builds its configuration at startup.
Public clients use PKCE S256. The realm includes confidential service clients
for Harness API, Control Centre and Model Gateway. Workspace tokens target
Harness API; Admin Console tokens target Control Centre. Harness API service
tokens target Control Centre and Model Gateway; Model Gateway service tokens
target Control Centre. Control Centre has no explicit audience mapper.
`ooh.smoke` carries free-form test messages, without an event envelope.

## Versions

| Component | Exact version/image | Purpose |
|---|---|---|
| k3s | `v1.36.6+k3s1` | Kubernetes with Traefik and local storage; installed by server setup |
| cert-manager | `v1.21.3` | Staging and production TLS issuance |
| Strimzi | `1.3.1` | Kafka operator; watches its `ooh-platform` namespace |
| Kafka | `4.3.2`, `quay.io/strimzi/kafka:1.3.1-kafka-4.3.2` | Broker and temporary smoke client |
| CloudNativePG | `1.30.0` | PostgreSQL operator |
| PostgreSQL | `ghcr.io/cloudnative-pg/postgresql:18.4-system-trixie` | Operator's pinned default; database and temporary SQL client |
| Keycloak/operator | `26.8.2` | OIDC identity, realm import and admin management |
| Placeholder image | `nginxinc/nginx-unprivileged:1.28.0-alpine` | Four non-root static pages |

PostgreSQL's exact image comes from the pinned operator's
[version source](https://github.com/cloudnative-pg/cloudnative-pg/blob/v1.30.0/pkg/versions/versions.go)
and [release notes](https://github.com/cloudnative-pg/cloudnative-pg/blob/v1.30.0/docs/src/release_notes/v1.30.md).
Operator download URLs are pinned in `install/10-platform-operators.sh`; each
must return HTTP 200 before it is applied. Downloads retry up to five times with
a five-second delay, including connection failures. Only HTTP 404 is reported as
`not found`; other failures include the final HTTP status and curl exit code.
Strimzi uses the official installation files from tag `1.3.1`.
The scripts use existing server tools (bash, curl, jq, OpenSSL, kubectl, getent,
awk, sed, sort, find); no additional system package installation is required.
