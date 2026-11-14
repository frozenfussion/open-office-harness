# QUICK GUIDE

## Stage 4 — Traces, replay and class demos

Claude runs the scripts in the harness terminal, Shell tile, plain shell while
Aziz watches. No terminal password. Complete the existing Stage 3 setup first.
Use the merged `stage-4` worktree and build all nine images for that commit.
Replace `MERGED_IMAGE_TAG` below with that commit's first 12 characters.

1. **Deploy in this order.** Type this in your harness terminal. Use the plain
   shell; the first line selects the folder. This adds Jaeger, updates Kafka
   permissions, runs migrations and deploys the same image tag everywhere.
   Good result: Ready and `DONE` from every script. No new setup script is needed.

   ```bash
   cd ~/projects/worktrees/stage-4
   install/30-platform-apply.sh
   install/61-control-centre-deploy.sh MERGED_IMAGE_TAG
   install/65-model-gateway-deploy.sh MERGED_IMAGE_TAG
   install/67-harness-api-deploy.sh MERGED_IMAGE_TAG
   install/73-slides-worker-deploy.sh MERGED_IMAGE_TAG
   install/75-consumers-deploy.sh MERGED_IMAGE_TAG
   install/68-workspace-deploy.sh MERGED_IMAGE_TAG
   install/69-admin-console-deploy.sh MERGED_IMAGE_TAG
   ```

2. **Check before class.** Type this in your harness terminal. Use the plain
   shell in the folder selected below. These check platform, rights, chat, jobs,
   tracing and replay. Good result: every line PASS, then `DONE` per script.
   Checks 70, 77 and 78 make short **paid calls**. Check 78 briefly stops the
   Gateway, so **chat is unavailable** during its failure check. Never run 78
   during a class. It temporarily grants tier 1 to the check account and removes
   only the grant it created. It creates retained test conversations and files.

   ```bash
   cd ~/projects/worktrees/stage-4
   install/40-check-platform.sh
   install/62-check-control-centre.sh
   install/70-check-stage-2.sh
   install/77-check-stage-3.sh MERGED_IMAGE_TAG
   install/78-check-stage-4.sh MERGED_IMAGE_TAG
   ```

3. **Open a trace.** In Admin Console → Audit, find the request and click
   **Trace**. A chat trace shows Harness, Control Centre and Gateway. A Slides
   trace includes the worker and consumers. Select a span to see its allowed
   attributes. **Tracing is unavailable** means Jaeger cannot be reached: check
   its readiness and logs. **This trace has expired** means Jaeger no longer
   has it. Jaeger stores at most 20,000 traces in memory; a restart clears them.
   The permanent audit trail stays. Make another request to get a fresh trace.
   There is no public Jaeger address or separate sign-in.

4. **Replay by hand.** In Failed messages, filter by topic, select the matching
   Request ID, read its error and fix the cause. Click **Replay**, confirm and
   wait for `sent`. A Slides card failed with `worker_gave_up` can turn Ready.
   Other failed and rejected jobs stay final. The original envelope, event ID
   and correlation ID stay the same; replay gets the admin request's trace.
   The replay count/history and an audit row record each attempt. A failed
   Kafka send records a failed attempt; check Kafka before retrying.
   Non-JSON messages and `dlq.chat.messages` cannot be replayed: the latter
   stores IDs only. Replaying to `skill.results` or `audit.events` also delivers
   to consumers that handled the event already; they drop it. The safety watcher
   may classify once more after a restart (one paid call); duplicate flags are
   still dropped by event ID.

5. **Show a worker outage.** Type this in your harness terminal. Use the plain
   shell in the folder below. The script stops only the Slides worker, then
   pauses for the presenter. Ask for slides in Workspace: chat answers, the card
   stays Queued, and the terminal shows `slides-worker pods: 0`. Press Enter to
   restore the worker; show Ready and download the file, then press Enter again.
   Good result: `DONE`. The successful job makes paid calls.

   ```bash
   cd ~/projects/worktrees/stage-4
   install/79-demo.sh worker-down MERGED_IMAGE_TAG
   ```

6. **Show a duplicate.** Type this in your harness terminal. Use the plain shell
   in the folder below. This publishes a Slides message, checks the first file,
   pauses, then sends the exact same message again. Press Enter at the pause.
   The audience sees one result ID and an unchanged file modification time.
   This direct Kafka demo creates no Workspace card. Good result: two PASS lines
   and `DONE`. Only the first job needs paid model calls.

   ```bash
   cd ~/projects/worktrees/stage-4
   install/79-demo.sh duplicate MERGED_IMAGE_TAG
   ```

7. **Show failure and recovery.** Type this in your harness terminal. Use the
   plain shell in the folder below. **Chat is unavailable while the Gateway is
   down.** Follow the pauses: open Workspace and Failed messages; the worker
   stops; ask for slides and wait for Queued and the completed chat; press Enter;
   the Gateway stops and the worker returns; wait for Failed and its dead letter;
   press Enter to restore the Gateway; click Replay and confirm; show Ready and
   download the file; press Enter to finish. Recovery makes paid calls.
   Good result: `DONE` and both services restored to their recorded counts.

   ```bash
   cd ~/projects/worktrees/stage-4
   install/79-demo.sh dead-letter MERGED_IMAGE_TAG
   ```

   To have the script find and replay the newest `worker_gave_up` Slides dead
   letter received after it stopped the Gateway, use the command below instead.
   It waits at most 120 seconds for that dead letter; the other presenter pauses
   remain. Avoid unrelated Slides requests during this demo.

   Type this in your harness terminal. Use the plain shell in the folder below.
   This performs the same demo with automatic replay; good result: PASS and `DONE`.

   ```bash
   cd ~/projects/worktrees/stage-4
   install/79-demo.sh dead-letter MERGED_IMAGE_TAG --auto
   ```

8. **Stop safely or recover.** Press Ctrl+C in the running script. EXIT, Ctrl+C,
   TERM and HUP restore recorded replica counts. If the terminal or machine was
   killed before cleanup, use the command below. No image tag or check client
   is needed. The manifest count is **1 for each service**.

   Type this in your harness terminal. Use the plain shell in the folder below.
   This restores the Gateway and worker to their manifest counts and waits for
   Ready; good result: `DONE`. Then run the platform check from step 2.

   ```bash
   cd ~/projects/worktrees/stage-4
   install/79-demo.sh restore
   ```

9. **Check the Workspace fixes.** Copy a `/?conversation=<uuid>` link, open it
   signed out, then sign in: the saved conversation should open once. An invalid
   ID is ignored. Ask for a Markdown table: words stay whole and a wide table
   scrolls sideways; ordinary text still wraps long IDs. In the dead-letter demo,
   watch a failed `worker_gave_up` card become Ready without refreshing; reload
   and confirm it stays Ready.

10. **After a reboot.** Allow five minutes for recovery, then repeat step 2.
    Jaeger's old traces will be gone; the audit records and output files remain.
    Use the existing status, logs, start, stop and restart commands below for
    the application services. For Jaeger status and logs:

    Type this in your harness terminal. The folder does not matter for these
    commands. Use the plain shell. This shows readiness and recent Jaeger logs;
    good result: one Ready replica and no repeated configuration errors.

    ```bash
    kubectl -n ooh-platform get deployment jaeger
    kubectl -n ooh-platform logs deployment/jaeger --tail=100
    ```

### Stage 4 STOP and FAIL help

| Message or failed check | What to do |
|---|---|
| Usage / invalid demo or image tag | Use one of the exact forms above with a 12-character lower-case commit tag. `--auto` is only for dead-letter. |
| Missing tool / local settings / contact email | Complete the server setup and private settings steps below. Do not enter credentials in Codex. |
| All application images / readiness | Build all nine images for the merged commit, keep them public and deploy the same tag in step 1. Inspect the failing Deployment's status and logs. |
| Jaeger Ready / OTLP round-trip / query API | Re-run 30 after fixing Jaeger config/readiness. Inspect its logs; 4318 and 16686 are internal only. |
| SKIP Jaeger round-trip (Slides worker not deployed yet) | Expected before deploying the application services: Jaeger readiness is still checked. Deploy Slides with step 1, then rerun 40 to check the OTLP round-trip. |
| INFO jaeger restarted N times | Informational: traces may have expired. Check memory and logs if restarts repeat. |
| Gateway or worker scaled to 0 / already stopped / could not restore | Run the restore command in step 8 and check readiness before retrying. |
| Temporary check client / another check running / check token | Let the other check finish. If none runs, re-run 35 to repair the client, then retry. Check Keycloak privately. |
| Check client did not disable / still enabled | Run a stage check to completion and then 40; inspect the helper and Keycloak privately if it persists. |
| Check-user tier grant failed / temporary grant could not be removed | Check the active tier 1 entry and rights service. Remove only this run's new check-user grant in People & rights. |
| Check conversation / saved chat / chat stream | Check Harness readiness, check-user approved access, tier 1 registry settings, rate limit and budget. |
| Chat audit rows / trace parent relationship | Check audit writer readiness and tracing settings in all services. Ensure the merged Parts are deployed; try a new request. |
| Traced Slides request / result / Kafka check | Check worker, Kafka, check-principal ACLs and an active chat model for Slides. Inspect pod logs privately. |
| Raw traces contain question/topic or forbidden fields/events | Stop the demonstration and fix the service's trace filter before retrying. |
| worker_gave_up result / no dead letter arrived; is the worker running? | Check the worker, its retry limit, Kafka and the Control Centre dead-letter consumer. Restore services before retrying. |
| Replay did not return 202 sent / automatic replay failed | Inspect the Failed messages response and Kafka permissions. Restore services, fix the cause and retry. |
| Replay count / replay audit row missing | Check Control Centre migration, audit writer and Kafka readiness. |
| Replayed job did not complete / file missing or invalid | Check worker, Gateway, model registry and retained volume permissions. Fix the cause and replay again. |
| Duplicate result differs / no fresh result / file time changed | Inspect worker idempotency. Do not continue the class demo until the same request reuses its result and file. |
| Malformed message / dead letter / non-JSON replay was not refused | Check worker validation and Control Centre replay validation; do not replay arbitrary malformed content. |
| `FAIL check pod result: expected exactly one OOH_RESULT JSON line` | The temporary check pod returned a missing, duplicate or invalid result. Other log lines are ignored. Retry the check; if it repeats, ask the builder to inspect that check pod's result output. This applies to the skills check, tracing check and demos. |
| Input closed / step failed / cannot continue / trace hop or privacy check failed / Stage 4 checks failed | Cleanup runs automatically. Fix the last failed check, restore if needed and retry from the start. |

The Stage 3 guide below remains the setup and everyday operations reference.
For Stage 4 deployment and checks use the order above.

## AWS copy — Stage 4 phase 2

The AWS copy runs the same nine images as the class system, tag `7c721a4de601`,
on EKS in Singapore. The Droplet stays the main class system.
The copy costs about **USD 0.42/hour or USD 10.10/day**, plus traffic (about
USD 0.30 for each full image pull). Forgotten for a month, about USD 310.
Destroy it after the checks. Terraform builds and removes AWS resources;
Kafka, PostgreSQL and Keycloak still run inside Kubernetes.

Claude runs these commands in the Shell tile while Aziz watches. No command
asks for a sudo password. Step 6 asks Aziz to make up a password for the new
AWS administrator. Aziz handles browser authentication,
the first administrator's details, provider keys, and approval of costs. Run
from the reviewed, merged `stage-4b` worktree, after both Parts are reviewed.
Never run the AWS steps while a Codex builder is working: the short-lived root
session is readable by every process running as the same Unix user.

1. **Install the tools, then sign in.** Type this in your harness terminal,
   Shell tile, plain shell. This installs the pinned tools without sudo, then
   starts AWS sign-in. Good result: `DONE` from both scripts. Aziz approves the
   browser request and types the authentication code in his browser, as the
   sign-in script instructs. Never type or paste it in the Shell tile or chat;
   Claude does not handle the code. Always use this sign-in script: it records
   the sign-in time.

   ```bash
   cd ~/projects/worktrees/stage-4b
   install/80-aws-tools.sh
   install/83-aws-login.sh
   ```

2. **Make the state bucket and budget.** Type this in your harness terminal,
   Shell tile, plain shell. This shows the plan and its cost before building.
   On the first run Aziz supplies the budget email privately. After Aziz's yes
   in chat, Claude types `yes` at the script prompt. Good result: `DONE`.
   Aziz must click the AWS confirmation email immediately; otherwise budget
   alerts may never arrive. This email rule still needs live confirmation.
   The USD 40 budget warns at 50%, 80%, 100% actual and 100% forecast;
   it does not stop spending. Alerts may arrive 8–24 hours late. Read the AWS
   Billing page at every progress update too.

   ```bash
   cd ~/projects/worktrees/stage-4b
   install/81-aws-bootstrap.sh
   ```

3. **Build the cluster and front door.** Type this in your harness terminal,
   Shell tile, plain shell. This takes about 20–30 minutes. Terraform prints
   resource progress and waits for the control plane, node, add-ons and load
   balancer. Good result: `DONE` and the three CNAME records to add.
   The total cost appears before the first prompt. Aziz's one yes covers the
   three shown build steps at the fixed expected cost; Claude types `yes` at
   each script prompt. Any unexpected paid resource, replacement or failed
   root-access proof stops for a new decision. Do not bypass that stop.

   ```bash
   cd ~/projects/worktrees/stage-4b
   install/82-aws-cluster.sh
   ```

4. **Point the three names at AWS.** Do this in the DigitalOcean control panel.
   Claude adds these records after Aziz's yes. In the `faysalaziz.com` zone,
   use type **CNAME**, TTL **300**, and the load balancer hostname printed by
   the cluster script as the value for every row. Keep the Droplet's records.

   | Record name | Value |
   |---|---|
   | `harness.aws` | Load balancer hostname printed by the cluster script |
   | `admin.aws` | Same hostname |
   | `auth.aws` | Same hostname |

   Type this in your harness terminal, Shell tile, plain shell. This waits for
   the records and checks HTTP reaches Traefik. Good result: three DNS `PASS`
   lines, HTTP `PASS`, then `DONE`.

   ```bash
   cd ~/projects/worktrees/stage-4b
   install/84-aws-dns.sh
   ```

5. **Install the platform.** Type this in your harness terminal, Shell tile,
   plain shell. This selects AWS, checks its identity before any cluster work,
   installs the same operators, makes new secrets and empty databases, and
   requests staging certificates followed by production certificates.
   Good result: every script ends with `DONE`; the platform check prints `PASS`.
   The first line of each platform/app script must say `TARGET aws (EKS copy)`.
   Each run freezes its kubeconfig; child scripts reuse it. A different endpoint
   or node provider stops the run before it can change the wrong system.

   ```bash
   cd ~/projects/worktrees/stage-4b
   export OOH_TARGET=aws
   install/00-check-server.sh
   install/10-platform-operators.sh
   install/20-platform-secrets.sh
   install/30-platform-apply.sh
   install/35-realm-sync.sh
   install/40-check-platform.sh
   ```

6. **Create the first administrator.** Type this in your harness terminal,
   Shell tile, plain shell. Aziz runs this step himself and types the requested
   administrator details privately. It asks for the AWS first administrator's
   username, email and a new password (hidden, typed twice). This is not the
   sudo password and not the Droplet admin's password. This administrator is
   separate from the Droplet. Only an existing human administrator skips this
   step; service accounts do not count. Good result: `DONE` and sign-in works at
   `https://admin.aws.faysalaziz.com` after the apps are deployed.

   ```bash
   cd ~/projects/worktrees/stage-4b
   export OOH_TARGET=aws
   install/50-first-admin.sh
   ```

7. **Prepare and deploy the apps in this order.** Type this in your harness
   terminal, Shell tile, plain shell. This makes each service's private settings,
   runs migrations and installs the class images. Good result: each script
   ends with `DONE`, with the intended image tag. Run one script at a time:
   one node has little spare CPU during an update.
   Realm sync also runs inside platform apply. Keep the early sync above and
   repeat it after the Control Centre and Harness are Ready, as the Stage 2
   fresh-install guide requires, before deploying the browser apps.

   ```bash
   cd ~/projects/worktrees/stage-4b
   export OOH_TARGET=aws
   install/59-control-centre-databases.sh
   install/60-control-centre-secrets.sh
   install/63-control-centre-keys.sh
   install/71-control-centre-oidc.sh
   install/61-control-centre-deploy.sh 7c721a4de601
   install/64-model-gateway-setup.sh
   install/65-model-gateway-deploy.sh 7c721a4de601
   install/66-harness-api-setup.sh
   install/67-harness-api-deploy.sh 7c721a4de601
   install/35-realm-sync.sh
   install/68-workspace-deploy.sh 7c721a4de601
   install/69-admin-console-deploy.sh 7c721a4de601
   install/72-slides-worker-setup.sh
   install/73-slides-worker-deploy.sh 7c721a4de601
   install/74-consumers-setup.sh
   install/75-consumers-deploy.sh 7c721a4de601
   ```

   Aziz signs in at `https://admin.aws.faysalaziz.com`. In Models & tiers,
   configure tier 1, tier 2 and classification, entering provider keys himself.
   Give his account the Slides grant in People & rights. Keys never go into
   chat, a terminal command, a report or a repository file.
   AWS test database settings and the certificate email live under
   `~/.config/ooh/aws/`; the Droplet's settings stay under `~/.config/ooh/`.
   The check lock stays shared, so checks for the two systems cannot overlap.

8. **Check the copy and try it in the browser.** Type this in your harness
   terminal, Shell tile, plain shell. These include small paid model calls.
   Good result: `PASS` (plus the checks' allowed `INFO`/`SKIP` lines), then `DONE`.
   The AWS check reminds Aziz to confirm his budget email. Record actual
   results in the stage report; a local render pass does not prove live AWS.

   ```bash
   cd ~/projects/worktrees/stage-4b
   export OOH_TARGET=aws
   install/62-check-control-centre.sh
   install/70-check-stage-2.sh
   install/77-check-stage-3.sh 7c721a4de601
   install/78-check-stage-4.sh 7c721a4de601
   install/86-check-aws.sh
   ```

   Aziz opens `https://harness.aws.faysalaziz.com` and
   `https://admin.aws.faysalaziz.com`: sign in, chat on tier 1 and Auto, make and
   download a Slides deck, and open a trace in Audit. All three web names must
   have valid certificates. An independent read-only audit follows.

9. **Prove a lost node recovers.** Type this in your harness terminal,
   Shell tile, plain shell, only after Aziz's yes. This ends the worker instance
   and waits up to 25 minutes for its replacement and disks. The script prints
   the measured recovery time; copy that actual time into the instructor notes
   (not measured during the Part B build). Good result: `DONE`, followed by
   passing platform, Control Centre and AWS checks without manual cluster fixes.

   ```bash
   cd ~/projects/worktrees/stage-4b
   export OOH_TARGET=aws
   install/86-check-aws.sh --replace-node
   install/40-check-platform.sh
   install/62-check-control-centre.sh
   install/86-check-aws.sh
   ```

10. **Everyday status and logs.** Type this in your harness terminal,
    Shell tile, plain shell. These read AWS explicitly; exporting `OOH_TARGET`
    selects install scripts but does not change an interactive kubectl context.
    While `OOH_TARGET=aws` is set, every script works only on the AWS copy and
    refuses the Droplet, so check the `TARGET` first line before any Droplet work.
    Good result: Ready pods and JSON application logs. Read the AWS Billing
    page and budget at each update. AWS restarts pods automatically after node
    recovery; use the replacement check above for the recovery proof.

    ```bash
    cd ~/projects/worktrees/stage-4b
    export OOH_TARGET=aws
    kubectl --kubeconfig="$HOME/.kube/ooh-aws.config" get pods -A
    kubectl --kubeconfig="$HOME/.kube/ooh-aws.config" -n ooh-apps logs deployment/harness-api --tail=30
    ```

    Type this in your harness terminal, Shell tile, plain shell. These are
    offline syntax, lint and render checks; no AWS sign-in is needed. Good
    result: no lint errors and both renders end with `DONE`, hashes and zero
    invalid manifests. The standard schema check skips these operator kinds:
    ClusterIssuer, Kafka, KafkaNodePool, KafkaTopic, KafkaUser, Cluster,
    DatabaseRole, Database, Keycloak and KeycloakRealmImport. It preserves
    Keycloak's lower-case placeholders.

    ```bash
    cd ~/projects/worktrees/stage-4b
    bash -n install/lib/target.sh
    shellcheck -x install/*.sh install/lib/*.sh
    OOH_TARGET=do install/30-platform-apply.sh --check
    OOH_TARGET=aws install/30-platform-apply.sh --check
    ```

11. **Destroy after acceptance, then check the bill.** Type this in your
    harness terminal, Shell tile, plain shell. After Aziz accepts the stage,
    the reviewed merge is tagged `eks-ready`; after his separate yes Claude
    types `yes` at the destroy prompt. This shows saved destroy plans, removes
    the load balancer and test data, then destroys the Terraform stack. The
    AWS copy's databases, topics, files and address logs are intentionally
    removed; the Droplet is untouched. Good result: no leftovers and `DONE`.
    The state bucket and budget stay. Destroy logs out of AWS at the end.

    ```bash
    cd ~/projects/worktrees/stage-4b
    install/85-aws-destroy.sh
    ```

    Do this in the DigitalOcean control panel. Claude removes only the three
    `harness.aws`, `admin.aws`, `auth.aws` CNAME records after Aziz's yes.
    Read the AWS Billing page to confirm the copy's charges stopped; billing
    updates can lag. Keep the budget email confirmation.

    Type this in your harness terminal, Shell tile, plain shell. Sign in again
    to repeat the read-only leftover sweep at any time, then log out. Good
    result: `PASS`, `DONE`, with only the state bucket and budget retained.
    After logout and the reset below, the next Droplet script's first line
    says `TARGET do (Droplet, live class system)`.
    To start the copy again later, repeat this guide from sign-in and bootstrap;
    the next copy starts with empty application data.

    ```bash
    cd ~/projects/worktrees/stage-4b
    install/83-aws-login.sh
    install/85-aws-destroy.sh --sweep-only
    aws logout
    unset OOH_TARGET
    ```

12. **End every AWS work block by logging out.** Type this in your harness
    terminal, Shell tile, plain shell. The folder does not matter for logout;
    the `cd` below keeps the guide in one place. This removes the cached session
    before any Codex work resumes and resets script selection to the Droplet.
    No password. Good result: signed out; the next Droplet script's first line
    says `TARGET do (Droplet, live class system)`.
    Sign in through the sign-in script again before the next AWS work block.

    ```bash
    cd ~/projects/worktrees/stage-4b
    aws logout
    unset OOH_TARGET
    ```

### AWS STOP and FAIL help

| Message | What to do |
|---|---|
| `OOH_TARGET must be do or aws` | Set `OOH_TARGET=aws` for the copy or `do` for the Droplet, then retry. |
| `child script target differs from its parent` | Keep one target for the entire run. Retry the parent with the intended target. |
| `frozen kubeconfig is missing` | Retry the parent script; do not reuse freeze markers from a finished run. |
| `this shell points at ... not the ... cluster; nothing was changed` (including unexpected node provider) | Check the target values and kubeconfig. Do not bypass the check. AWS must match the endpoint written by the cluster script and a Singapore zone-a node; Droplet must use localhost and k3s. |
| `aws nodes are not Ready` / Traefik pod not Ready | Wait for the node (`install/86-check-aws.sh`, node readiness) and the Traefik release from `install/82-aws-cluster.sh`, then retry. |
| `no node is registered yet` | Wait for node creation or replacement, then retry. |
| `cannot read kubeconfig` / `cannot read cluster endpoint` / `cannot read nodes` | Check the selected kubeconfig and access. For AWS refresh sign-in if needed. |
| `AWS local settings missing` / `cannot read AWS local settings` / `AWS endpoint missing` / `AWS load balancer name missing` | Complete the cluster script before platform setup; it writes the local settings. |
| `missing tool` | Complete the existing server setup and AWS tools step; do not bypass the check. |
| `local settings missing` / contact email invalid or empty | Bootstrap copies the certificate email to `~/.config/ooh/aws/do.env`; fix that private file for AWS, or `~/.config/ooh/do.env` for the Droplet. |
| `invalid deployment value` | Correct the target's values file using the stage spec. Droplet `RETAIN_VOLUMES` must be exactly `true`. |
| `unknown deployment token` | A manifest has an unsupported upper-case placeholder. Ask the builder to fix its allowed renderer token list or the typo. |
| DNS lookup, CNAME or HTTP front-door failure | Check the three CNAME values, TTL, load balancer readiness and inbound ports 80/443. Never point the AWS names at the Droplet. |
| File binding / storage / PV retention failure | Check EBS CSI, its region and Pod Identity role, `ooh-gp3`, encryption, Delete policy and file-pod identity 10001. Droplet remains local-path, Retain, identity 1001. |
| Certificate pending | Check DNS and inbound port 80, then cert-manager events. Wait out a reported rate limit. |
| `AWS sign-in expired` or sign-in time missing/older than 11 hours | Run the sign-in script again; Aziz authenticates. Retry the stopped script. |
| Account differs from state bucket | Stop. Check the account and private backend settings before retrying. |
| Root access / admin proof failed | Stop before creating the node. Ask Aziz about destroying the control plane and the proposed sign-in change. |
| Unexpected paid create, delete or replacement in a plan | Stop for Aziz's new decision and cost approval. |
| No launch template found / sweep tag absent | Stop and ask Aziz using the stage spec's review path. The copy keeps costing about USD 0.42/hour while paused. |
| AWS check `FAIL` | Fix the named failed item and rerun. Address forwarding, disk encryption/tags, version, state locking and leftover failures must pass before acceptance. |
| Destroy failure / `DependencyViolation` / leftover resource | Keep the IDs private where they contain account details. Claude inspects the named dependency and follows the spec's approved cleanup, then reruns destroy; it resumes from Terraform state. |

## Stage 3 — Skills, jobs and admin screens

Claude runs the non-sudo scripts below in the harness terminal, Shell tile,
plain shell, while Aziz watches. No terminal password. First complete the
Stage 0–2 setup below, including database, encryption and service credentials.
Use the merged `stage-3` worktree. Replace `MERGED_IMAGE_TAG` with the merge
commit's first 12 characters. Run all nine image workflows for that commit;
wait for green builds. The same tag must exist for every image, including in
phase 2. These steps also apply after merging the routing Part.

1. **Prepare the platform and service credentials.** Type this in your harness
   terminal, Shell tile, plain shell. This adds the Kafka users/topics, mounts
   the branded sign-in theme, updates the realm, and prepares service Secrets
   and the consumers' private test databases. Good result: every script says
   `DONE`; the temporary check client stays disabled.

   ```bash
   cd ~/projects/worktrees/stage-3
   install/30-platform-apply.sh
   install/35-realm-sync.sh
   install/66-harness-api-setup.sh
   install/64-model-gateway-setup.sh
   install/72-slides-worker-setup.sh
   install/74-consumers-setup.sh
   ```

2. **Make the four new image packages public.** Aziz uses the GitHub package
   settings after their first green build: Change visibility → Public for
   [Slides worker](https://github.com/users/frozenfussion/packages/container/ooh-slides-worker/settings),
   [Audit writer](https://github.com/users/frozenfussion/packages/container/ooh-audit-writer/settings),
   [Cost meter](https://github.com/users/frozenfussion/packages/container/ooh-cost-meter/settings), and
   [Safety watcher](https://github.com/users/frozenfussion/packages/container/ooh-safety-watcher/settings).
   Good result: the images pull without signing in. Keep the five existing
   packages public too.

3. **Deploy the merged images.** Type this in your harness terminal, Shell tile,
   plain shell. This runs migrations, starts the services, registers the Slides
   manifest and updates both apps. Good result: Ready and `DONE` each time.
   Deployment itself makes no paid model calls.

   ```bash
   cd ~/projects/worktrees/stage-3
   install/61-control-centre-deploy.sh MERGED_IMAGE_TAG
   install/65-model-gateway-deploy.sh MERGED_IMAGE_TAG
   install/67-harness-api-deploy.sh MERGED_IMAGE_TAG
   install/73-slides-worker-deploy.sh MERGED_IMAGE_TAG
   install/75-consumers-deploy.sh MERGED_IMAGE_TAG
   install/68-workspace-deploy.sh MERGED_IMAGE_TAG
   install/69-admin-console-deploy.sh MERGED_IMAGE_TAG
   ```

4. **Grant Slides and add a classifier.** Aziz opens
   [People & rights](https://admin.faysalaziz.com) and ticks Slides for himself,
   then saves. In Models & tiers, add purpose **classification**. Choose
   **Jev System One** with your Jev service endpoint and its model identifier,
   or a chat connection type with that service's endpoint and model identifier.
   Enter any required key privately in the Console. Classification has no tier.
   Set prices and limits for the saved entry. Test connection makes a short
   **paid** call; good result: Works with time and a score. All endpoints,
   model identifiers and keys are entered there, never into repository files.

5. **Run the live checks.** Type this in your harness terminal, Shell tile,
   plain shell. This checks the platform, Control Centre, chat and Stage 3.
   Checks 70 and 77 make short **paid** calls. Check 77 makes a Slides job,
   repeats it, sends a synthetic safety example, tests classification, and
   makes four Auto chat turns plus classification and title calls, temporarily grants
   tier 1 and tier 2 to the check account, then removes grants created by this run.
   It needs active tier 1 and tier 2 chat entries and no broader check-account or
   Everyone tier grant for the tier-1-only test. It also makes up to four calls
   per chat connection type (including the retry when
   thinking prevents a forced tool). Good result: all PASS, then `DONE`.
   INFO safety scores need not create a flag; the check clears its own flag.
   A download ownership check says `SKIP no other user's job yet` only when the
   Harness database has no other-user job; complete the browser test below.
   Check 62 uses the temporary admin client and needs no browser sign-in.

   ```bash
   cd ~/projects/worktrees/stage-3
   install/40-check-platform.sh
   install/62-check-control-centre.sh
   install/70-check-stage-2.sh
   install/77-check-stage-3.sh MERGED_IMAGE_TAG
   ```

6. **Check the browser flows.** In Workspace ask for slides, watch Queued turn
   to Ready, then Download and open the PowerPoint file. Jobs and the chat card
   show its topic and Request ID; Copy copies the full ID for the Audit filter.
   With another account without Slides, use Chat model → Skills → Request a
   skill… and Send request. Approve it in the Admin Console's Approvals screen;
   refresh Workspace to load the new grant. That account must get 404 if it
   opens the first account's job download address. Check Overview figures,
   service health, People & rights changes, and Audit by the full Request ID.
   Choose **Auto** in Chat model: a simple question should show `auto → tier 1`.
   A hard question should use tier 2 when granted; otherwise the meta line says
   an admin can give you tier 2. Ask for slides with the Slides right on a tier
   whose main entry accepts forced tools: the job should start. If the model
   declines a tool when forcing was unavailable, the meta line says
   "The model chose not to use Slides." Routing scores appear in Audit under
   action `route`; routing, chat and title calls share the user message id.
   Explicit model choices bypass routing.

7. **Tune safety.** Edit `deploy/apps/safety-watcher/configmap.yaml`: change
   `SF_QUESTIONS` (JSON) or `SF_THRESHOLD` (0–1). Keep thresholds and questions
   in the ConfigMap. Type this in your harness terminal, Shell tile, plain
   shell. This applies the new settings; good result: Ready and `DONE`.

   ```bash
   cd ~/projects/worktrees/stage-3
   install/75-consumers-deploy.sh MERGED_IMAGE_TAG
   ```

   To tune Auto routing, edit `deploy/apps/harness-api/configmap.yaml`:
   `HA_ROUTE_TIER_QUESTION` contains Aziz's rule for careful multi-step reasoning
   (rigorous proofs or hard maths, complex code, debugging or architecture design,
   deep expert analysis or comparisons with trade-offs), rather than facts, short
   writing, translations, summaries or everyday questions.
   `HA_ROUTE_TIER_THRESHOLD` is 0.5, `HA_ROUTE_UP_TIER` is 2, and
   `HA_ROUTE_SKILL_THRESHOLD` is 0.8 by default. `HA_ROUTE_TIMEOUT_SECONDS`
   limits the routing call to 30 seconds by default; a timeout uses the lowest
   allowed tier with the routing-unavailable note. Scores at or above a threshold
   qualify. The [calibration rule, labelled set and measured scores](docs/routing/README.md)
   document this choice; re-run the set when the classifier, question or threshold
   changes. Skill questions come from allowed skills' descriptions. Keep these
   settings in the ConfigMap. Type this in your harness terminal, Shell tile,
   plain shell. This loads the routing settings; good result: Ready and `DONE`.

   ```bash
   cd ~/projects/worktrees/stage-3
   install/67-harness-api-deploy.sh MERGED_IMAGE_TAG
   ```

   When routing is unavailable, Auto uses the lowest allowed tier and says so.
   Rights still decide every tier and skill. Auto keeps thinking on; choose an
   explicit tier to use that tier's thinking switch. Scores and routing notes
   are saved with the assistant answer and remain visible after reloading.

8. **Status and images.** Type this in your harness terminal, Shell tile,
   plain shell. This shows which image each service is running and whether it
   is ready. Good result: all Deployments have their requested ready replicas.

   ```bash
   cd ~/projects/worktrees/stage-3
   kubectl -n ooh-apps get deployments -o wide
   kubectl -n ooh-apps get pods
   ```

9. **Read logs.** Type this in your harness terminal, Shell tile, plain shell.
   This reads the last 100 log lines for each new service. Logs contain IDs and
   status, never prompts, keys or file contents.

   ```bash
   cd ~/projects/worktrees/stage-3
   kubectl -n ooh-apps logs deployment/slides-worker --tail=100
   kubectl -n ooh-apps logs deployment/audit-writer --tail=100
   kubectl -n ooh-apps logs deployment/cost-meter --tail=100
   kubectl -n ooh-apps logs deployment/safety-watcher --tail=100
   ```

10. **Restart.** Type this in your harness terminal, Shell tile, plain shell.
    Claude runs it while Aziz watches. This restarts each new service and waits
    until it is ready. Good result: successfully rolled out. Kafka retains
    queued work while a worker is down; the chat keeps answering.

    ```bash
    cd ~/projects/worktrees/stage-3
    kubectl -n ooh-apps rollout restart deployment/slides-worker deployment/audit-writer deployment/cost-meter deployment/safety-watcher
    kubectl -n ooh-apps rollout status deployment/slides-worker --timeout=300s
    kubectl -n ooh-apps rollout status deployment/audit-writer --timeout=300s
    kubectl -n ooh-apps rollout status deployment/cost-meter --timeout=300s
    kubectl -n ooh-apps rollout status deployment/safety-watcher --timeout=300s
    ```

11. **Stop or start one new service.** Type this in your harness terminal,
    Shell tile, plain shell. Claude runs it while Aziz watches. To stop the
    Slides worker, use the first command; to start it, use the second and wait
    for Ready. The same commands work with `audit-writer`, `cost-meter` or
    `safety-watcher` in place of `slides-worker`. Stopping does not delete data.

    ```bash
    cd ~/projects/worktrees/stage-3
    kubectl -n ooh-apps scale deployment/slides-worker --replicas=0
    kubectl -n ooh-apps scale deployment/slides-worker --replicas=1
    kubectl -n ooh-apps rollout status deployment/slides-worker --timeout=300s
    ```

12. **After a reboot.** Wait up to five minutes for Kubernetes to bring the
    services back. Run step 5 again, then the browser checks in step 6. Never
    rerun first-admin setup to recover an existing account. New administrators
    keep the password they enter; it is not temporary.

13. **Run the Workspace checks locally.** Type this in your harness terminal,
    plain shell, in the merged Stage 3 worktree. This installs the locked
    packages, builds and runs the tests without changing the cluster. Good result: build
    succeeds, all tests pass. Use the merged worktree for the combined checks.

    ```bash
    cd ~/projects/worktrees/stage-3/apps/workspace
    npm ci
    npx ng build
    npx ng test --watch=false
    ```

Files stay on the retained `ooh-files` volume (20Gi). The Slides worker writes
`outputs/slides/<request-id>/<safe-title>.pptx`; the Harness mounts it read-only
and serves authenticated `GET /api/jobs/<job-id>/file` after checking ownership.
No signed links. Uploads remain unavailable. Nothing deletes generated files.

### Stage 3 STOP and FAIL help

| Message or failed check | What to do |
|---|---|
| `STOP: another check is running` | Wait for it, or remove a stale lock only when its PID is gone (the script does this itself). Do not stop a running check to borrow its credentials. |
| `FAIL ooh-stage-check enabled with no check running` | Run `install/77-check-stage-3.sh <tag>` once (it takes over the stale lock and disables the client on exit), then run 40 again. |
| Check client missing, unavailable, invalid ID or cannot enable/disable; check token unavailable, request failed or lacks audience | Inspect Keycloak readiness; run 35 again when no check is running, then retry. Never print the secret or token. A disable failure leaves the lock held for exit cleanup to retry. |
| `FAIL ooh-stage-check still enabled` / `STOP: check client did not disable` | Restore Keycloak connectivity, run 77 once to disable and rotate credentials, then run 40. |
| `STOP: KafkaUser <name> not ready; re-run 30` | Run 30 and inspect the KafkaUser status, then repeat that service's setup. |
| Secret changed / differs from Keycloak or Kafka | Inspect privately; never overwrite a live credential blindly. Setup scripts preserve existing matching values. |
| Missing tool, invalid value, usage or missing local settings | Finish server setup or correct the named setting. Use a 12-character merge image tag and the command shown above. |
| Pod or Deployment not ready; wrong image tag; image pull failure | Inspect status and logs, run the workflow for the merge commit, make its package public, deploy with the same tag. |
| Realm branding, device sign-in or login stylesheet | Run 30 then 35. Inspect `ooh-keycloak-theme` and the Keycloak theme mount. No custom Keycloak image is needed. |
| Kafka ACLs or thirteen topics | Compare `contracts/identity.md`, then run 30. Do not grant wildcard topic/group rights. |
| `FAIL check pod result: expected exactly one OOH_RESULT JSON line` | The temporary check pod returned a missing, duplicate or invalid result. Other log lines are ignored. Retry the check; if it repeats, ask the builder to inspect that check pod's result output. |
| Slides request/result, repeat ID, file or modification-time check | Inspect worker and Gateway health, model configuration, budget and `ooh-files` permissions. Worker writes as UID 10001; it creates its own output folder. |
| Malformed message not in dead letters | Inspect worker DLQ publication and the Control Centre consumer; retry after both are Ready. |
| Trail missing, Overview cost not a number | Inspect audit writer/cost meter and their database migrations; run 35 for the Control Centre's custom audiences. |
| `no classification model: add one in Models & tiers` | Add an active classification entry and Test connection, then rerun 77. |
| Classifier or safety scores unavailable | Inspect classifier configuration, Gateway budget/rate limit and safety watcher logs; adjust settings only through ConfigMaps/registry. |
| Model did not call the tool with thinking on (auto), tool round or new question failed | Inspect that registry entry's tool support and budget, and the Gateway adapter's reasoning history. The check retries once when forcing was not applied. |
| Unknown/malformed/other-user download is accepted | Stop acceptance and fix the Harness ownership/path check. Never grant access to pass the test. |
| Cannot read another-user job ID as harness_app | Inspect its Secret reference, app-role database access and the jobs migration; no password should be copied to a terminal. |
| Port busy / port-forward not ready | Wait for the previous check to finish, inspect service readiness and retry; do not start another check on its port. |
| Service health not OK | Inspect that service's pod and logs; wait for the next 30-second health refresh. |
| Test safety flag could not be cleared | Clear only this check's flag in Approvals, then retry. |
| Any remaining `STOP: ...` / `cannot continue after ...` | Fix the preceding named FAIL or readiness problem, then rerun the same script. It is safe to repeat; keep existing data and secrets. |

The Stage 2 instructions below describe its original deployment. On Stage 3,
use the sequence above: 62 uses the temporary check client, device sign-in is
disabled, and a newly entered first-admin password needs no forced change.

### Routing check messages

- A routing simple/hard question FAIL means its scores, selected tier, saved
  routing metadata or access note differed from the expected result. Inspect
  `route` scores in Audit, classifier settings, and active chat tier models.
- `STOP: routing check needs only tier 1` means the check account already has
  another tier, possibly through Everyone. Review those grants in People &
  rights before retrying; the script never removes pre-existing grants.
- A temporary routing grant FAIL means Control Centre could not grant or remove
  this run's check-account rights. Review those grants in People & rights.
  Cleanup retries on every exit before disabling the temporary client.
- Before the phase 2 deployment, run all nine image workflows **on demand for
  the final merge commit**, wait for green builds, and run every deploy script
  again with its 12-character tag using the order above. Building only the two
  changed images does not satisfy the image check.

## Stage 2 — Talk to AI

Claude runs the non-sudo deploy and live-check commands in the Shell tile while
Aziz watches. No command here asks for a terminal password. Aziz keeps browser
sign-ins, package visibility changes, sudo and stage acceptance. Before this
stage, complete the Stage 0 platform and Stage 1 Control Centre setup below.
The existing Control Centre test database is reused. Fresh Stage 2 setup uses
**63 → 71 → 61 → 64 → 65 → 66 → 67 → 35 → 68 → 69 → add models → 62 → 70**.

For the Request access update on an existing Stage 2 deployment, use the new
Control Centre, Harness and both app image tags. Type this in your harness
terminal, Shell tile, plain shell. Claude runs these commands while Aziz watches;
no terminal password. This installs the access rule before opening registration,
then updates both screens and checks the result. The Control Centre check asks
for no browser sign-in; it uses the temporary check client. Good result: each script ends with
`DONE`, and checks print `PASS`. The paid-call note in the live-check step applies.
If Test connection is not installed yet, prepare 71 and deploy the new Gateway
with 65 before this sequence.

```bash
cd ~/projects/worktrees/stage-2
install/61-control-centre-deploy.sh MERGED_IMAGE_TAG
install/67-harness-api-deploy.sh MERGED_IMAGE_TAG
install/35-realm-sync.sh
install/68-workspace-deploy.sh MERGED_IMAGE_TAG
install/69-admin-console-deploy.sh MERGED_IMAGE_TAG
install/62-check-control-centre.sh
install/70-check-stage-2.sh
```

1. **Check images and make the four new packages public.** On GitHub, wait for
   green image workflows for Gateway, Harness, Workspace and Admin Console.
   Each tag is the image commit's first 12 characters. A merged commit needs all
   four images; run a workflow on demand for `stage-2` if its path filter did
   not start it. Claude opens each package's settings in a new tab in Aziz's
   PC browser; Aziz clicks **Change visibility → Public**:
   [Gateway](https://github.com/users/frozenfussion/packages/container/ooh-model-gateway/settings),
   [Harness](https://github.com/users/frozenfussion/packages/container/ooh-harness-api/settings),
   [Workspace](https://github.com/users/frozenfussion/packages/container/ooh-workspace/settings),
   [Admin Console](https://github.com/users/frozenfussion/packages/container/ooh-admin-console/settings).
   Do this before deploying the Gateway. Control Centre stays public as before.

2. **Set up keys.** Type this in your harness terminal, Shell tile, plain shell.
   Claude runs it while Aziz watches. No password. This creates the encryption
   Secret once; good result: `DONE`.

   ```bash
   cd ~/projects/worktrees/stage-2
   install/63-control-centre-keys.sh
   ```

3. **Set up the Control Centre service credentials.** Type this in your harness
   terminal, Shell tile, plain shell. Claude runs it while Aziz watches. No
   password. This reads the client secret inside Keycloak and creates the private
   `control-centre-oidc` Secret once. Good result: `DONE`. It keeps a matching
   existing Secret and stops if it differs from Keycloak; inspect privately
   rather than replacing it blindly. Without credentials the Control Centre
   still starts, but Test reports that service credentials are missing.

   ```bash
   cd ~/projects/worktrees/stage-2
   install/71-control-centre-oidc.sh
   ```

4. **Deploy the Control Centre.** Type this in your harness terminal, Shell tile,
   plain shell. No password. Replace `MERGED_IMAGE_TAG` with the image commit's
   first 12 characters in each deploy step. This upgrades the registry and its
   database; good result: Ready, then `DONE`.

   ```bash
   cd ~/projects/worktrees/stage-2
   install/61-control-centre-deploy.sh MERGED_IMAGE_TAG
   ```

5. **Set up the Gateway.** Type this in your harness terminal, Shell tile, plain
   shell. No password. This prepares its roles, databases and secrets; good
   result: private test settings saved, then `DONE`.

   ```bash
   cd ~/projects/worktrees/stage-2
   install/64-model-gateway-setup.sh
   ```

6. **Deploy the Gateway.** Type this in your harness terminal, Shell tile, plain
   shell. No password. This runs migrations and starts the internal Gateway;
   good result: Ready, then `DONE`.

   ```bash
   cd ~/projects/worktrees/stage-2
   install/65-model-gateway-deploy.sh MERGED_IMAGE_TAG
   ```

7. **Set up the Harness.** Type this in your harness terminal, Shell tile, plain
   shell. No password. This prepares its roles, databases and secrets; good
   result: private test settings saved, then `DONE`.

   ```bash
   cd ~/projects/worktrees/stage-2
   install/66-harness-api-setup.sh
   ```

8. **Deploy the Harness.** Type this in your harness terminal, Shell tile, plain
   shell. No password. This runs migrations and replaces the API placeholder;
   good result: Ready, then `DONE`.

   ```bash
   cd ~/projects/worktrees/stage-2
   install/67-harness-api-deploy.sh MERGED_IMAGE_TAG
   ```

9. **Update sign-in and sign-out settings.** Type this in your harness terminal, Shell tile,
   plain shell. No password. This updates existing Keycloak clients, including
   logout redirects, Test connection audience, registration, user profile,
   password policy and English texts. It never creates a client. Registration
   opens by default. Run this only after the new Control Centre and Harness
   are Ready. Good result: verified settings and clients, then `DONE`.

   ```bash
   cd ~/projects/worktrees/stage-2
   install/35-realm-sync.sh
   ```

10. **Deploy Workspace.** Type this in your harness terminal, Shell tile, plain
    shell. No password. This replaces the chat page placeholder; good result:
    the intended running image, then `DONE`.

    ```bash
    cd ~/projects/worktrees/stage-2
    install/68-workspace-deploy.sh MERGED_IMAGE_TAG
    ```

11. **Deploy Admin Console.** Type this in your harness terminal, Shell tile,
    plain shell. No password. This replaces the admin placeholder and removes
    its leftover placeholder settings; good result: Ready, then `DONE`.

    ```bash
    cd ~/projects/worktrees/stage-2
    install/69-admin-console-deploy.sh MERGED_IMAGE_TAG
    ```

12. **Add models in the browser.** Open <https://admin.faysalaziz.com>, sign in
    with your administrator account password, choose **Add model**, then enter
    a title, purpose, chat tier, main/backup role, order, location, connection
    type, endpoint and the model ID supplied by your provider. These are example
    addresses for the form only; no model name or endpoint is compiled into an app.

    | Connection | Example endpoint | Example model ID |
    |---|---|---|
    | OpenAI Responses (`openai_responses`) | `https://api.openai.com/v1` | `<your-model-id>` |
    | Anthropic Messages (`anthropic_messages`) | `https://api.anthropic.com` | `<your-model-id>` |
    | DeepSeek via chat completions (`openai_chat_completions`) | `https://api.deepseek.com` | `<your-model-id>` |
    | DeepSeek via Messages (`anthropic_messages`) | `https://api.deepseek.com/anthropic` | `<your-model-id>` |
    | On-prem via chat completions (`openai_chat_completions`) | `http://<host>:8000/v1` | `<your-model-id>` |

    Type the provider key once. Save; the list says only whether a key is saved,
    and an edit form never fills it back in. Changing its endpoint or connection
    type clears the saved key unless a replacement is typed in the same save.
    Set rate limit per user, daily budget (0 = no limit), input/output prices per
    million tokens in USD and the time limit. Extra request settings must be a
    JSON object; a null value removes a provider field. `temperature`, `top_p`
    and `top_k` may be refused by newer Anthropic versions. At least one keyed
    chat entry per connection type is needed for the full browser acceptance test.
    Click **Test** beside a saved model to send one short paid call to that entry.
    Without a saved key, it is disabled with **Save a key first**. While waiting
    it says **Testing…**. A successful result shows seconds, a short reply, token
    counts and cost. A failure shows a plain reason and, when available, the
    provider status and redacted message. Results stay until the next test or
    reload. The key is never sent to the browser. Tests count against the entry's
    daily budget and rate limit.

13. **Give people a tier.** On that tier's **Who may use this tier** row, switch
    **Everyone** on, or enter the person's user ID and add them. They can copy
    their ID from Workspace's **About me** line under their name. In Workspace,
    sign in, choose an allowed tier, ask a question and check streaming, token
    counts and conversation reload. Adding a person by user ID also approves
    their access, including a previously rejected person. Request access stores
    the form's name, email and organisation now; user-ID grants do not look up
    Keycloak. Everyone grants work only for approved people.

14. **Check access rules and the Control Centre.** Type this in your harness
    terminal, Shell tile, plain shell. Claude runs it while Aziz watches. No
    terminal password. Sign in as an administrator using the browser link.
    This checks the access rule, including Everyone grants; good result: all
    `PASS`, then `DONE`.

    ```bash
    cd ~/projects/worktrees/stage-2
    install/62-check-control-centre.sh
    ```

15. **Run the live check.** Type this in your harness terminal, Shell tile,
    plain shell. Claude runs it while Aziz watches. No password or device
    sign-in. It checks all keyed entries in chat tiers 1–20, public restrictions,
    usage rows, logs, the registration form and the reserved access-check user.
    The access check creates no Keycloak person and reuses `stage-check-access`;
    its status must not be approved. **Each run makes one short paid call per entry with a
    key, plus one streamed paid call per connection type in use, plus one pinned
    paid call as the Control Centre.** The extra Control Centre call is skipped
    with a note when no keyed chat entry is found; the full stage check still
    requires keyed chat entries. Keep tier 98
    empty for the no-model check. Good result: every line `PASS`, then `DONE`.

    ```bash
    cd ~/projects/worktrees/stage-2
    install/70-check-stage-2.sh
    ```

16. **Everyday work and builder checks.** Each guide below gives exact commands
    for logs, restart, running images, setup, tests and every STOP/FAIL message.
    Use the merged worktree until acceptance, then `~/projects/open-office-harness`.
    Do not stop databases or the platform to stop an app.

    - [Gateway guide](services/model-gateway/README.md): Python checks and Gateway operations.
    - [Harness guide](services/harness-api/README.md): Python checks and Harness operations.
    - [Workspace guide](apps/workspace/README.md): `npm ci`, Angular build/tests, chat operations and all stage-check messages.
    - [Admin Console guide](apps/admin-console/README.md): Angular build/tests, models, keys and grants.
    - [Control Centre guide](services/control-centre/README.md): registry, encryption key recovery and private backup.

17. **After a reboot.** k3s starts everything automatically. Wait five minutes.
    Type this in your harness terminal, Shell tile, plain shell. Claude runs it
    while Aziz watches. No terminal password; the Control Centre check asks for
    browser administrator sign-in. This repeats platform, policy and chat checks;
    good result: all `PASS`, each ending with `DONE`. The paid-call note above
    applies again. Then check browser chat. Only Aziz runs the reboot itself,
    using the Stage 0 reboot instructions below.

    ```bash
    cd ~/projects/worktrees/stage-2
    install/40-check-platform.sh
    install/62-check-control-centre.sh
    install/70-check-stage-2.sh
    ```

Stage-check failures for **unpinned**, **streamed** or **other-messages Control
Centre call** mean the Gateway must enforce its restricted test-call rules
(HTTP 403, `forbidden`). A failure for **Control Centre pinned test call** means
Claude should check realm sync, service-account audience, the saved key, rate
limit and daily budget privately. See the [Control Centre guide](services/control-centre/README.md)
for 71's STOP messages; a changed client secret needs private inspection.

### Request access and approvals

A newcomer opens <https://harness.faysalaziz.com> and clicks **Sign in with
company account**. On Keycloak's login page, **Need access? Request access** opens
the registration form. The apps keep their single sign-in button; passwords
are entered only in Keycloak. Enter first name, last name, work email (also the
username), an optional organisation or team, an optional reason of at most 300 characters,
and a chosen password twice. Passwords must be 12–128 characters and cannot be
the username or email. There is no email verification or password-reset mail.

After registration the Workspace shows
`Thanks, <first name>. Your request is waiting for approval.` It shows no chat or conversations. At 100 waiting
requests, it shows **Requests are closed for now. Please contact your
administrator.** A rejection or revocation shows **Your request was not approved.
Please contact your administrator.** These screens offer only **Sign out**.
If the access service fails, a red notice is shown instead of a waiting message.

An admin opens <https://admin.faysalaziz.com> and selects **Access requests**.
Waiting requests are first, newest first; the badge is hidden at zero. Select a
chat tier for a request, then press **Approve**, or press **Reject**. No tier is
preselected; tier 99 is hidden. Approved rows have **Revoke**, and rejected rows
can be approved again. Every email is labelled **not verified**. Refresh the
Workspace after approval to open chat. Admins are approved automatically; adding
a person by user ID to a tier also approves them. Everyone grants never bypass
approval. Existing users who had only Everyone must request access once: sign
in to Workspace to create their waiting request, then have an admin approve it.
People and explicit user grants known before the migration are backfilled.

Organisation and reason can be edited through the Account Console; the Control
Centre copies them only while the request is pending. Email is the username and
cannot be changed by the user with these realm settings. The Account Console
remains reachable at <https://auth.faysalaziz.com/realms/ooh/account>.

**If registration spam appears:** Type this in your harness terminal, Shell
tile, plain shell. Claude runs it while Aziz watches. No password. This closes
new registrations while retaining accounts and requests. Good result:
`Registration off`, verified settings, then `DONE`.

```bash
cd ~/projects/worktrees/stage-2
install/35-realm-sync.sh --registration off
```

Type this in your harness terminal, Shell tile, plain shell. Claude runs it
while Aziz watches. No password. This reopens registration after the cause is
addressed; good result: `Registration on`, verified settings, then `DONE`.

```bash
cd ~/projects/worktrees/stage-2
install/35-realm-sync.sh --registration on
```

Running 35 without a flag also opens registration, including when platform apply
calls it. Keep that in mind while registration is intentionally closed.
The registration-page check in 70 expects registration to be open.

**Reset someone's password:** In your browser, open the Keycloak Admin Console
at <https://auth.faysalaziz.com/admin/> and sign in with your Keycloak
administrator account password. Select realm **ooh** → **Users** → the person →
**Credentials** → **Reset password**. Set a replacement password with
**Temporary** on, and give it to the person privately. Their next sign-in asks
them to choose a password. No mail server is needed; the Account Console stays
reachable.

| New STOP/FAIL message | What to do |
|---|---|
| `usage: install/35-realm-sync.sh` | Use no arguments, or exactly `--registration off` or `--registration on`. |
| `registration settings could not be verified` | Inspect realm ooh's login and password-policy settings privately; repeat 35 after fixing the cause. |
| `user profile response is invalid`, `user profile could not be verified` | Inspect the profile and unmanaged-attribute policy; preserve unrelated fields before retrying 35. |
| `registration texts could not be verified` | Inspect the realm's English text overrides; retry 35. |
| `registration attribute mappers could not be verified` | Inspect organisation/access_reason mappers on ooh-workspace; they must be access-token-only. |
| `FAIL Workspace registration page` | Check 35 ran after 61 and 67, registration is on, and both extra form fields are present. |
| `FAIL access check user is not approved` | Check the observe route and reserved stage-check-access row privately; never approve that check user. |

Keycloak 26.8.2's [default profile configuration](https://github.com/keycloak/keycloak/blob/26.8.2/services/src/main/resources/org/keycloak/userprofile/config/keycloak-default-user-profile.json)
is retained for fresh installs, with two attributes added in the realm's
UserProfileProvider component under `kc.user.profile.config`. For existing
realms, 35 reads and updates [the user profile API](https://www.keycloak.org/docs-api/26.8.2/rest-api/index.html#_get_adminrealmsrealmusersprofile),
keeping every other attribute and unmanaged policy. Its
[email edit condition](https://github.com/keycloak/keycloak/blob/26.8.2/services/src/main/java/org/keycloak/userprofile/DeclarativeUserProfileProviderFactory.java)
prevents an existing user editing email with email-as-username on and edit-username
off. The fields are user-editable in Keycloak 26, rather than registration-only.

## Stage 1 — Control Centre

From Stage 2, Claude runs deployment and live-check scripts that need no sudo
in the Shell tile while Aziz watches. Aziz runs every sudo command himself.
Use the Shell tile, plain shell, for every command below. None of these scripts
asks for a password.
After acceptance, everyday work uses `~/projects/open-office-harness` on `main`.
During the build and testing, use the folder shown for your phase below. Pushing
the merged `stage-1` branch builds the image with its exact 12-character commit tag.
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

2. **Make the databases.** This creates the live and test databases, each
   with a separate owner and app role. No password. Good result: four roles and
   two databases meet their condition, private test settings are saved, then
   `DONE`. Use the command for your current phase.

   **Before the merge:** Type this in your harness terminal, Shell tile, plain
   shell. This runs the database setup from Part B.

   ```bash
   cd ~/projects/worktrees/stage-1-part-b
   install/59-control-centre-databases.sh
   ```

   **After the merge, before acceptance:** Type this in your harness terminal,
   Shell tile, plain shell. This runs the database setup from the merged code.

   ```bash
   cd ~/projects/worktrees/stage-1
   install/59-control-centre-databases.sh
   ```

   **After acceptance:** Type this in your harness terminal, Shell tile, plain
   shell. This runs the database setup from the main clone.

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
   terminal. The shared helper enables the temporary admin client, rotates its
   secret, obtains fresh tokens in memory and disables it on exit. No browser
   sign-in is required. A second simultaneous check is refused.
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
   before the reboot. Allow five minutes. These commands check the platform,
   then the Control Centre; its check uses the temporary admin client again. No password.
   Good result: both scripts finish with `DONE` and no `FAIL` lines.

   **Until Stage 1 is accepted:** Type this in your harness terminal, Shell
   tile, plain shell. This runs the reboot checks from the merged code.

   ```bash
   cd ~/projects/worktrees/stage-1
   install/40-check-platform.sh
   install/62-check-control-centre.sh
   ```

   **After acceptance:** Type this in your harness terminal, Shell tile, plain
   shell. This runs the reboot checks from the main clone.

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
    | Image not found or not public | Check that the workflow run for this commit is green, then switch the ooh-control-centre package to Public (README step 3). |
    | Registry unreachable or registry check failed | Check ghcr.io availability and retry. |
    | Registry returned an invalid token | Retry; inspect ghcr.io availability if it continues. |
    | Unexpected admin certificate issuer | Inspect the existing admin Ingress; keep the certificate managed by that Ingress. |
    | Deployment, revision or migrations not Ready | Read migration and pod logs above. Check the public package and exact tag. Never edit an applied migration. |
    | Keycloak CLI login or client secret unavailable | Inspect Keycloak readiness and bootstrap access privately; the named existing client must exist. |
    | Service token for a client: Keycloak refused the client credentials | Inspect that client's Keycloak credentials and service-account settings privately; fix them and repeat 62. No API check ran for that failed token request. |
    | Service token endpoint unreachable or no valid access token returned | Check Keycloak availability and its token endpoint; fix the token failure before repeating 62. |
    | KafkaTopic partition count could not be read or is invalid | Inspect the named KafkaTopic and its spec.partitions, then retry. |
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
   password when asked. A repeat run leaves an existing human administrator
   unchanged; service accounts do not count.

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
| `do nodes are not Ready` / `aws nodes are not Ready`, kubectl access error | Check kubectl access; wait for k3s after a Droplet reboot (do) or the EKS node (aws). |
| `DNS lookup failed`, `does not resolve only to` | Correct the named A record to 143.198.221.2 or wait for DNS to spread. |
| `Traefik pod is missing or not Ready` | Inspect Traefik pods in kube-system and wait for them to become Ready. |
| `target Traefik request failed`, `no HTTP status from` | Check the Droplet's Traefik and ServiceLB (do) or the load balancer (aws). HTTP and HTTPS must return a status; 404 is normal before ingress routes exist. |
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
audience mappers are removed, including the Control Centre's self audience.
Its Model Gateway audience is retained for the restricted pinned test call.
Verification reads both included client and custom audiences and
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
target Control Centre. Control Centre service tokens target Model Gateway for
only the pinned, non-streamed fixed test call; the mapper adds the audience to
access tokens, not ID tokens.
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
