# QUICK GUIDE

1. **What this is.** Open Office Harness is an open-source office AI platform.
   Stage 0 installs its foundation; the apps are placeholder pages. The Droplet
   runbook lives in the course's own private notes, outside this repository.

2. **Set up the server once.** Only Aziz runs setup and deployment commands.
   Type this in your harness terminal, in the `shell` tile (plain shell, not Codex).
   The folder doesn't matter for this command. This downloads the repository.
   No password is requested for this public clone.

   ```bash
   git clone https://github.com/frozenfussion/open-office-harness.git ~/projects/open-office-harness
   ```

   Type this in your harness terminal, `shell` tile, plain shell. This enters the
   clone and installs server tools. It will ask for harness's sudo password.
   Good result: the setup script ends with `DONE`.

   ```bash
   cd ~/projects/open-office-harness
   sudo install/01-server-setup.sh
   ```

   Type this in your harness terminal, `shell` tile, plain shell. The folder
   doesn't matter. This loads kubectl access in this terminal and signs Git into
   GitHub. Follow GitHub's browser sign-in instructions; no sudo password.

   ```bash
   export KUBECONFIG="$HOME/.kube/config"
   gh auth login
   gh auth setup-git
   ```

   Type this in your harness terminal, `shell` tile, plain shell. This enters
   Part B's worktree and creates private local settings **only if missing**.
   No password. Good result: the file opens; fill in `LETSENCRYPT_EMAIL`, leave
   `SPACES_REGION=sgp1` and `SPACES_BUCKET=ooh-files`, then save and exit the editor.
   Do not put Spaces keys in this file. The firewall must allow incoming TCP
   22, 80 and 443; Aziz sets it in DigitalOcean. The bucket must be private.

   ```bash
   cd ~/projects/worktrees/stage-0-part-b
   mkdir -p ~/.config/ooh
   (umask 077; test -e ~/.config/ooh/do.env || cp install/ooh.env.example ~/.config/ooh/do.env)
   nano ~/.config/ooh/do.env
   ```

   The remaining guide commands use this Part B worktree until review and merge.
   After merge, use `cd ~/projects/open-office-harness` instead.

3. **Check the server.** Type this in your harness terminal, `shell` tile, plain
   shell. This checks the node, local settings, DNS, Traefik pod readiness and
   local HTTP/HTTPS responses. Any HTTP status (including 404) is good here;
   the local HTTPS check allows Traefik's initial untrusted certificate.
   No password. Good result: all `PASS` lines, then `DONE`.

   ```bash
   cd ~/projects/worktrees/stage-0-part-b
   install/00-check-server.sh
   ```

4. **Install operators.** Type this in your harness terminal, `shell` tile, plain
   shell. This installs the pinned platform operators and waits for them.
   No password. Good result: deployments successfully rolled out, then `DONE`.

   ```bash
   cd ~/projects/worktrees/stage-0-part-b
   install/10-platform-operators.sh
   ```

5. **Create secrets.** Type this in your harness terminal, `shell` tile, plain
   shell. This generates database and bootstrap passwords and asks for your
   Spaces access key and secret key with hidden input. No sudo password.
   Good result: each secret says `Created` or `Already exists`, then `DONE`.
   Secrets are never displayed or overwritten. Never paste them into Codex.

   ```bash
   cd ~/projects/worktrees/stage-0-part-b
   install/20-platform-secrets.sh
   ```

6. **Apply the platform.** Type this in your harness terminal, `shell` tile, plain
   shell. This creates the foundation and placeholder pages. No password.
   Allow several minutes. `Waiting for Kafka` and `Waiting for certificate`
   messages are normal. Staging certificates prove Let's Encrypt can reach the
   server from outside; only then does the script request production certificates.
   Good result: resources become Ready, then `DONE`. A repeat run preserves
   production issuers and existing data.

   ```bash
   cd ~/projects/worktrees/stage-0-part-b
   install/30-platform-apply.sh
   ```

7. **Check the platform.** Type this in your harness terminal, `shell` tile, plain
   shell. This checks pods, trusted HTTPS, issuer, all eleven topics, Kafka rights,
   database access and Spaces read/write. No password. It creates temporary check
   pods and removes them. Small objects under `checks/` stay in Spaces.
   Good result: every line says `PASS`, then `DONE`.

   ```bash
   cd ~/projects/worktrees/stage-0-part-b
   install/40-check-platform.sh
   ```

8. **Create the first admin.** Type this in your harness terminal, `shell` tile,
   plain shell. This asks for username, email and password twice (password hidden).
   No sudo password. Good result: `First admin created`, then `DONE`.
   Open <https://auth.faysalaziz.com/realms/ooh/account>, sign in and change the
   password when asked. A repeat run leaves an existing administrator unchanged.

   ```bash
   cd ~/projects/worktrees/stage-0-part-b
   install/50-first-admin.sh
   ```

9. **Everyday tasks.** Type this in your harness terminal, `shell` tile, plain
   shell. The folder doesn't matter. This lists pods; no password.
   Good result: running pods show Ready; completed setup jobs may show Completed.

   ```bash
   kubectl get pods -A
   ```

   Type this in your harness terminal, `shell` tile, plain shell. The folder
   doesn't matter. This reads Workspace logs; no password.

   ```bash
   kubectl -n ooh-apps logs deployment/workspace --tail=50
   ```

   Type this in your harness terminal, `shell` tile, plain shell. The folder
   doesn't matter. This restarts Workspace and waits for it; no password.
   Good result: `successfully rolled out`.

   ```bash
   kubectl -n ooh-apps rollout restart deployment/workspace
   kubectl -n ooh-apps rollout status deployment/workspace --timeout=300s
   ```

   Type this in your harness terminal, `shell` tile, plain shell. The folder
   doesn't matter. This stops the Workspace placeholder only; no password.
   Kafka, PostgreSQL and Keycloak remain running; do not scale them to stop apps.

   ```bash
   kubectl -n ooh-apps scale deployment/workspace --replicas=0
   ```

   Type this in your harness terminal, `shell` tile, plain shell. The folder
   doesn't matter. This starts the Workspace placeholder; no password.
   Good result: `successfully rolled out`.

   ```bash
   kubectl -n ooh-apps scale deployment/workspace --replicas=1
   kubectl -n ooh-apps rollout status deployment/workspace --timeout=300s
   ```

   After a reboot, k3s starts the platform automatically. Wait five minutes,
   then repeat step 7. For the stage's reboot test, Aziz alone runs the following.
   Type this in your harness terminal, `shell` tile, plain shell. The folder
   doesn't matter. This reboots harness; it will ask for harness's sudo password.

   ```bash
   sudo reboot
   ```

10. **Builder checks.** Type this in your harness terminal, `shell` tile, plain
    shell. This checks contracts (after Part A is merged), shell files and YAML.
    No password. Good result: tests pass, shell tools print no errors, YAML has
    zero errors. Custom resource kinds are explicitly skipped by kubeconform;
    their actual admission and readiness checks happen during Aziz's deployment.

    ```bash
    cd ~/projects/worktrees/stage-0-part-b
    uv run --project contracts/check pytest
    uv run --project contracts/check ruff check contracts/check
    uv run --project contracts/check ruff format --check contracts/check
    for script in install/*.sh; do bash -n "$script"; done
    shellcheck install/*.sh
    kubeconform -strict -summary -skip ClusterIssuer,Kafka,KafkaNodePool,KafkaTopic,KafkaUser,Cluster,DatabaseRole,Database,Keycloak,KeycloakRealmImport deploy/platform
    ```

11. **If a script stops.** Read the table below. Stop at the first failed step;
    send Codex the `STOP:` or `FAIL` line without secrets. Fix the reason, then
    run that same step again. Never loop certificate requests when rate limited.

| Message contains | What to do |
|---|---|
| `local settings missing` | Create the settings file in step 2. |
| `local setting ... is empty`, `contact email is invalid`, `unsupported characters` | Open the local settings file and fill in a valid email. |
| `Spaces settings must name sgp1 and ooh-files` | Correct the region and bucket in local settings. |
| `missing tool` | Ask Aziz to finish server setup; Codex does not install system tools. |
| `k3s node is not Ready`, kubectl access error | Check server setup and kubectl access; wait for k3s after reboot. |
| `DNS lookup failed`, `does not resolve only to` | Correct the named A record to 143.198.221.2 or wait for DNS to spread. |
| `Traefik pod is missing or not Ready` | Inspect Traefik pods in kube-system and wait for them to become Ready. |
| `local Traefik request failed`, `no HTTP status from` | Inspect Traefik and ServiceLB. Local HTTP and HTTPS must return a status; 404 is normal before ingress routes exist. |
| `<url> not found` | The server returned HTTP 404 after retries. Send the URL to Codex; verify the same version on the vendor's release page. Do not substitute a new version. |
| `<url> download failed (HTTP ...; curl exit ...)` | Retries were exhausted. HTTP 504 or another server error can be temporary; wait and rerun the same script. HTTP 000 means no HTTP response; check connectivity and the curl error. |
| `Spaces keys are empty` | Repeat step 5 with both keys. Hidden input is normal. |
| `required secret missing` | Run step 5 first. |
| `certificate pending for` | Check DNS and DigitalOcean inbound TCP 80/443; inspect cert-manager events and logs. Staging issuance is the real outside check. |
| `production certificate pending` | Inspect certificate events. If rate limited, wait for the stated limit window before retrying. |
| `step failed; see README` | Read the immediately preceding tool error. Check operator/pod events, connectivity, storage and memory; send the error to Codex. No changes are rolled back or deleted. |
| `admin request failed` | Check Keycloak readiness and bootstrap secret; re-run step 8. A partly created marked first-admin account gets its role completed without changing its password. |
| `username/email/password missing or passwords differ` | Repeat step 8 with nonempty username, valid email and matching passwords. |
| `username already exists` | Ask Aziz to inspect that account; the script will not overwrite an unrelated account. |
| `Spaces keys are missing or invalid` | Ask Aziz to inspect the Spaces Secret without printing its values. Step 5 never overwrites it. |
| `FAIL pods` | Check pending/crashing pods, memory, storage and operator logs. Completed jobs are excluded. |
| `FAIL production certificate`, `FAIL HTTPS` | Check ingress, deployment, DNS and certificate events; HTTPS must validate without bypassing TLS checks. |
| `FAIL OIDC issuer` | Check realm import, Keycloak hostname and `proxy.headers: xforwarded`. |
| `FAIL topic` | Re-run step 6; inspect the named KafkaTopic and Kafka readiness. |
| `FAIL Kafka smoke` | Inspect KafkaUser `ooh-smoke` and its ACLs. Only `ooh.smoke` is permitted; denial must specifically be a topic authorization error. |
| `FAIL PostgreSQL` | Inspect database/role status and the `keycloak-db` secret reference. Passwords must match; do not replace existing secrets blindly. |
| `FAIL storage` | Check the private bucket and its key's read/write permission, plus network access. The test object is retained. |
| `platform checks failed` | Fix every `FAIL` line above it, then repeat step 7. |

Type this in your harness terminal, `shell` tile, plain shell. The folder doesn't
matter. This shows platform events for troubleshooting; no password.

```bash
kubectl -n ooh-platform get events --sort-by=.metadata.creationTimestamp
kubectl -n cert-manager get events --sort-by=.metadata.creationTimestamp
```

## What is where

| Path | Contents |
|---|---|
| `deploy/platform/` | Namespaces, certificates, Kafka, PostgreSQL, Keycloak and placeholder manifests |
| `deploy/values/do.env` | Public deployment values; no credentials or personal contact data |
| `install/ooh.env.example` | Template for private local settings in `~/.config/ooh/do.env` |
| `install/00` through `install/50` scripts | Server check, operators, secrets, apply, checks, first admin |
| `docs/specs/` | Stage spec and global rules |
| `contracts/` | Module agreements and contract checks (Part A) |

Secrets exist in Kubernetes only; interactive inputs are held in process memory.
Kafka check credentials exist briefly in a temporary pod's in-memory volume.
No application or database data is removed by these scripts. All persistent
volumes use `local-path`; Kafka claims and database resources retain data.
The Keycloak realm import is for initial creation; it does not update an already
existing realm. Report any realm changes after first deployment before rerunning.
Public clients use PKCE S256. The realm includes confidential service clients
for Harness API, Control Centre and Model Gateway. Workspace tokens target
Harness API; Admin Console tokens target Control Centre. Harness API and Control
Centre service tokens include Control Centre and Model Gateway audiences.
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
must return HTTP 200 before it is applied. All operator downloads retry up to
five times with a five-second delay, including connection failures. Only HTTP
404 is reported as `not found`; other failures include the final HTTP status
and curl exit code. The first operator-install run created both namespaces,
then a transient GitHub HTTP 504 was incorrectly reported as a missing
cert-manager manifest. The retry and status handling corrects that failure.
Strimzi uses the individual official
files from tag `1.3.1`, avoiding reliance on an unavailable release-asset gateway.
The scripts use existing server tools (bash, curl, jq, OpenSSL, kubectl, getent,
awk, sed, sort); no new system package installation is added.

Spec clarifications from Claude, 09 Nov 2026: the server check tests Traefik pod
readiness and local HTTP/HTTPS responses; staging certificate issuance tests
outside reachability. ServiceLB forwards ports through iptables, so an `ss`
listener check incorrectly rejected a working Traefik installation. Aziz's first
run passed node access, settings and DNS but stopped on that listener check;
local requests returned Traefik's normal 404. The check now accepts any HTTP
status and allows the initial untrusted certificate only for local HTTPS. The realm
has a fifth confidential service client, `ooh-model-gateway`, with no redirects,
and the audience mappers described above. The smoke topic uses free-form test
messages with no schema or envelope. These are owner-supplied updates to the
written stage spec, not extra features.
