# QUICK GUIDE

1. **Set up the merged stage.** Follow the root README's Stage 3 order first. It
   covers realm sync, the existing database, Kafka and encryption Secrets, and
   the Control Centre service credential. Claude runs the non-sudo scripts in
   Aziz's shell tile. Keep credentials in Kubernetes Secrets. No credential is
   typed into this console's repository or a builder session.

2. **Deploy or start the Control Centre.** Type this in your harness terminal,
   in the plain shell; Claude runs it while Aziz watches. No password is needed.
   Be in the merged Stage 3 folder. This applies configuration and migrations,
   then waits for the image of this commit. Its image workflow must be green.
   Good result: the new revision is Ready and the script ends with `DONE`.

   ```bash
   cd ~/projects/worktrees/stage-3
   install/61-control-centre-deploy.sh
   ```

3. **Deploy or start the console.** Type this in your harness terminal, in the
   plain shell; Claude runs it while Aziz watches. No password is needed. This
   deploys the console for the same merged commit. Good result: the revision is
   Ready and `DONE`. After acceptance, use the main clone for everyday commands.

   ```bash
   cd ~/projects/worktrees/stage-3
   install/69-admin-console-deploy.sh
   ```

4. **Review work in the browser.** Open `https://admin.faysalaziz.com` on your PC
   and choose **Sign in with company account**. Enter your account password only
   on Keycloak's page. **Overview** opens first; a dash means a helper could not
   answer. **Approvals** combines all waiting decisions: select a row, read it,
   then decide. A sign-up needs a chat tier. Safety **Clear** means no problem;
   **Confirm problem** confirms a problem. **People & rights** has people across
   tiers and skills: change checks, then **Save**. Everyone grants also apply to
   approved people. **Audit** accepts the full request ID; select a row's request
   ID to read its complete trail in time order. Details follow this guide.

5. **Add or test a model.** In the same browser, open **Models & tiers**, then
   **Add model**. Enter its title, purpose, connection type, endpoint, model ID,
   main/backup role, priority, limits, prices, time limit and saved key. Chat
   entries have a tier; Classification entries do not. Extra request settings
   must be a JSON object. Thinking-off settings may be blank or a JSON object.
   Save, then **Test**. Test makes one short paid call to this saved entry only.
   A classification test shows a score. Keys stay encrypted, and never return
   to the browser. Changing an endpoint/type removes its key unless a replacement
   is entered. **Switch off** marks the row removed and keeps its history.

6. **Check status and the running image.** Type this in your harness terminal,
   in the plain shell. No password is needed; the folder does not matter. This
   shows both deployments. Good result: one Ready replica for each.

   ```bash
   kubectl -n ooh-apps get deployment admin-console control-centre -o wide
   ```

7. **Read logs.** Type this in your harness terminal, in the plain shell. No
   password is needed; the folder does not matter. This reads recent console
   logs. Good result: no startup errors. For backend errors, use the second line.

   ```bash
   kubectl -n ooh-apps logs deployment/admin-console --since=10m
   kubectl -n ooh-apps logs deployment/control-centre --since=10m
   ```

8. **Restart the console.** Type this in your harness terminal, in the plain
   shell; Claude runs it while Aziz watches. No password is needed; the folder
   does not matter. This replaces the console pod and waits for Ready again.

   ```bash
   kubectl -n ooh-apps rollout restart deployment/admin-console
   kubectl -n ooh-apps rollout status deployment/admin-console --timeout=600s
   ```

9. **Stop the console.** Type this in your harness terminal, in the plain shell;
   Claude runs it while Aziz watches. No password is needed; the folder does not
   matter. This stops the pod while retaining its configuration. Start again
   with step 3, which restores one replica.

   ```bash
   kubectl -n ooh-apps scale deployment/admin-console --replicas=0
   ```

10. **Build and test locally.** Type this in your harness terminal, in the plain
    shell. No password is needed. This installs the exact locked packages, copies
    design assets, builds and tests once. Good result: the build and every test
    pass. No server or watcher starts.

    ```bash
    cd ~/projects/worktrees/stage-3-part-d/apps/admin-console
    npm ci --no-audit --no-fund
    npx ng build
    npx ng test --watch=false
    ```

11. **After a reboot.** Kubernetes starts both apps itself. Wait up to five
    minutes, then use step 6. Claude runs the merged stage checks from the root
    README. You do not need to start a server or repeat secret setup.

| Message | What to do |
|---|---|
| `STOP: image not built yet` | Wait for this commit's image workflow to pass. |
| `STOP: image not found or not public` | Check the workflow, then make the corresponding GitHub container package Public in its package settings on your PC. |
| `STOP: registry is unreachable` or registry HTTP failure | Check connectivity to the registry and retry the deploy script. |
| `STOP: required application secret missing` | Follow root setup for existing database/Kafka Secrets. |
| `STOP: run install/63-control-centre-keys.sh` | Follow root encryption setup before deploying. |
| `STOP: current revision or migrations could not be verified` or new revision not Ready | Read pod and migration logs; resolve the reported startup problem, then redeploy. |
| `STOP: admin Ingress has an unexpected certificate issuer` | Have the maintainer inspect the existing Ingress before changing it. |
| `STOP: invalid deployment value`, usage, image-tag or missing-tool error | Correct the named input or finish server setup, then rerun. Tags have exactly 12 lowercase hexadecimal characters. |
| Connection test cannot sign in | Check realm sync, the existing Control Centre service credential and Gateway deployment. |
| Connection test says key refused or no credit | Replace the saved key or restore provider credit, then retry. |
| Connection test says rate limited or over daily budget | Wait for the limit window or UTC day, or adjust the entry's limits. |
| `This console is for administrators.` | Use the Workspace, or sign in with an administrator account. |
| Overview shows a dash or Audit says unavailable | Inspect the helper's status and service credential audiences, then Refresh or Filter again. |
| A decision or grant save fails | Read the error and retry. Successful grant changes have already been retained; only unsaved changes remain. |

# Stage 3 screens

Type this in your harness terminal, in the plain shell. No password is needed.
This installs the locked packages, builds the console and runs the tests once.
Good result: the build completes and all tests pass. No server is started.

```bash
cd ~/projects/worktrees/stage-3-part-d/apps/admin-console
npm ci --no-audit --no-fund
npx ng build
npx ng test --watch=false
```

After the merged stage is deployed, open the Admin Console and sign in with an
administrator account. **Overview** opens first. It shows today's active and
approved people, skill jobs, model calls and cost. A dash means the service that
supplies a figure could not answer. Refresh reads the latest figures; system
health is checked by the Control Centre every 30 seconds. Needs-attention links
open Approvals or Models & tiers. Failed-message attention counts the past day;
replaying messages and a Failed messages screen are outside this stage.

**Approvals** combines waiting sign-ups, model requests, skill requests, job
approvals and safety flags. Select a row to read it. A sign-up needs a chat tier
before Approve is available. Model and skill requests use Approve or Reject.
Jobs use Approve or Deny, with a note saved to audit. On a safety flag, Clear
means no problem (`approved: false`); Confirm problem means `approved: true`.
The flagged excerpt is shown as text. A failed decision stays selected for retry.
The navigation badge includes every waiting kind. Email addresses are not verified.

**People & rights** shows people, tiers and active skills, plus Everyone. Check
or clear individual grants, then Save. Discard drops unsaved changes. Everyone
also applies to every approved person; clearing a person's own grant does not
cancel an Everyone grant. Granting a person a right also approves access, as in
Stage 2. Service accounts and reserved check identities are hidden. Every grant
change uses the existing audited grant routes.

**Audit** accepts the full request UUID, a user ID and an action. Filter shows
newest rows first; Load more reads the next page. Select a request ID to load its
complete trail in time order. Scores, token counts and cost are shown when present.
If the audit service is unavailable, the screen shows its error and can be retried.

**Models & tiers** offers Chat and Classification. Classification hides the tier
field and adds Jev System One to the connection choices. Enter the endpoint and
model ID as registry data. Test makes one short paid call to that saved entry;
classification success reads `Works · <seconds> s · score <number>`. Health chips
show OK, Down with its reason/time, or Unknown.

Use the existing Quick Guide for deployment, status, logs, stop, start, restart
and recovery after reboot. The deploy scripts take the merged commit's 12-character
image tag. These screens add no package and retain the existing exact lock file.
