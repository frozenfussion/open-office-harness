# QUICK GUIDE

The AWS copy is temporary. It starts empty, uses the nine class images tagged
`7c721a4de601`, and keeps the Droplet running as the main class system. It costs
about **USD 0.42/hour, USD 10.10/day**, plus traffic. Destroy it after testing.
These steps are for Claude during the run phase, with Aziz watching. Aziz supplies
browser authentication and approvals in chat. No AWS session may exist while a
Codex builder works. No command below needs sudo or a terminal password.
During the run phase, use the merged worktree `~/projects/worktrees/stage-4b`,
as the commands below show. After acceptance and merge to main, the folder is
`~/projects/open-office-harness`; use `cd ~/projects/open-office-harness` instead.

1. **Install tools.** Type this in your harness terminal, in the plain shell.
   This installs the pinned tools under your home folder. Good result: `DONE`.

   ```bash
   cd ~/projects/worktrees/stage-4b
   install/80-aws-tools.sh
   ```

   The scripts load `~/.local/bin` themselves. For other commands in the same
   plain shell, load the permanent PATH setting now:

   ```bash
   export PATH="$HOME/.local/bin:$PATH"
   ```

2. **Sign in, only after every Codex builder has stopped.** Type this in your
   harness terminal, in the plain shell. Claude opens the printed link; Aziz
   approves and types the code in his browser. Good result: `DONE`.

   ```bash
   cd ~/projects/worktrees/stage-4b
   install/83-aws-login.sh
   ```

3. **Build the private state bucket and budget.** Type this in your harness
   terminal, in the plain shell. On the first run, Aziz enters the budget email.
   Claude shows the plan and cost, waits for Aziz's yes in chat, then types `yes`
   at the script prompt. Good result: `DONE`. Aziz confirms AWS's budget email
   immediately so alerts can arrive; alerts can be 8–24 hours late.

   ```bash
   cd ~/projects/worktrees/stage-4b
   install/81-aws-bootstrap.sh
   ```

4. **Build the AWS copy.** Type this in your harness terminal, in the plain
   shell. Good result: three reviewed plans, `DONE`, and three CNAME records.
   Allow about 25 minutes. Terraform prints its progress while it waits.
   The script shows the USD 0.42/hour total before the first plan. Each saved
   plan has its own `yes` prompt. Aziz's recorded approval covers all three
   only when their paid-resource counts match the agreed list or there are no
   paid creates or deletes on a re-run. Any paid delete still stops.

   ```bash
   cd ~/projects/worktrees/stage-4b
   install/82-aws-cluster.sh
   ```

   Before nodes are created, this proves root has full Kubernetes rights and
   checks EBS configuration keys against AWS's schema. If either fails, stop
   and take the stated action below. Record the masked Auto Scaling group and
   launch-template tags printed by the script in the stage status during the
   run phase. Never put an account number in the repository.

5. **Add DNS records, then check them.** Claude adds the three CNAME records
   printed by the build, TTL 300, at DigitalOcean after Aziz agrees. Type this
   in your harness terminal, in the plain shell. Good result: three `PASS`
   lines and `DONE`.

   ```bash
   cd ~/projects/worktrees/stage-4b
   install/84-aws-dns.sh
   ```

6. **Deploy and test the applications.** Follow the root README's AWS copy
   guide, after both Parts have been merged. It supplies the full platform and
   application order and the browser tests. Type this in your harness terminal,
   in the plain shell, after those deployments. Good result: thirteen `PASS`
   lines, the budget reminder, and `DONE`.

   ```bash
   cd ~/projects/worktrees/stage-4b
   install/86-check-aws.sh
   ```

7. **Test automatic node replacement, on Aziz's separate yes.** Type this in
   your harness terminal, in the plain shell. This ends the worker instance,
   waits up to 25 minutes for its replacement and mounted-volume pods, proves
   the old root disk is gone, reruns platform and Control Centre checks, and
   reruns the AWS checks. Good result: `PASS`, measured seconds and `DONE`.
   The Control Centre check may need Aziz's browser sign-in, as on the Droplet.

   ```bash
   cd ~/projects/worktrees/stage-4b
   install/86-check-aws.sh --replace-node
   ```

8. **Status or logs.** Type this in your harness terminal, in the plain shell.
   The folder does not matter. This reads the AWS copy only; good result: pods
   and their states. Set the dedicated kubeconfig on every manual command.

   ```bash
   kubectl --kubeconfig "$HOME/.kube/ooh-aws.config" get pods -A
   ```

   Type this in your harness terminal, in the plain shell; the folder does not
   matter. This reads Traefik logs, including the approved temporary address
   log. Good result: JSON log lines, with no request paths or credentials.

   ```bash
   kubectl --kubeconfig "$HOME/.kube/ooh-aws.config" -n kube-system logs deployment/traefik
   ```

   Read the AWS Billing page at every progress update; budget email is delayed.
   After a harness reboot, sign in again and check the existing copy. Do not
   create another copy. EKS starts replacement nodes itself. This stage has no
   separate manual stop/start/restart command: destroy to stop billing and
   rebuild with steps 2–6 when needed. For service recovery use the existing
   root README deployment commands with `OOH_TARGET=aws`.

9. **Destroy, after acceptance/tagging and Aziz's yes.** Type this in your
   harness terminal, in the plain shell. It shows both destroy plans and asks
   once before deleting AWS test data and resources. Good result: clean sweep,
   `DONE`. It keeps the private state bucket and budget, removes the AWS
   kubeconfig, clears the local endpoint/hostname, and logs out of AWS.

   ```bash
   cd ~/projects/worktrees/stage-4b
   install/85-aws-destroy.sh
   ```

   Claude then removes the three CNAME records after Aziz agrees. Read the
   Billing page to confirm charges have stopped. A failed destroy can be
   repeated: it reads Terraform state to resume the remaining work.

10. **Repeat the read-only sweep.** Sign in with step 2 if needed. Type this
    in your harness terminal, in the plain shell. Good result: no leftover
    copy resources, `PASS`, `DONE`. This checks all enabled regions and IAM.

    ```bash
    cd ~/projects/worktrees/stage-4b
    install/85-aws-destroy.sh --sweep-only
    ```

    Type this in your harness terminal, in the plain shell; the folder does not
    matter. This ends every AWS work block. Good result: the session is gone.

    ```bash
    aws logout
    ```

11. **Remove the state bucket and budget too, only on a separate yes.** Type
    this in your harness terminal, in the plain shell, after signing in. It
    performs the normal destroy, then shows a separate bootstrap destroy plan
    and asks a second question before removing the state history and budget.
    Good result: `DONE`. Keep the private bootstrap state until it completes.

    ```bash
    cd ~/projects/worktrees/stage-4b
    install/85-aws-destroy.sh --all
    ```

12. **Run builder checks with no AWS session.** Type this in your harness
    terminal, in the plain shell. Good result: no formatting/lint errors and
    three valid roots and 18 passing fixture tests. The fixtures stub every
    account/cluster call; these commands never contact AWS or a cluster.

    ```bash
    cd ~/projects/worktrees/stage-4b
    terraform fmt -check -recursive infra/terraform/aws
    for root in bootstrap cluster addons; do
      terraform -chdir="infra/terraform/aws/$root" init -backend=false -input=false
      terraform -chdir="infra/terraform/aws/$root" validate
      (cd "infra/terraform/aws/$root" && tflint --init && tflint)
    done
    for script in install/8*.sh; do bash -n "$script"; done
    shellcheck -x install/8*.sh
    uv run --project contracts/check --frozen python infra/terraform/aws/cluster/tests/review_fixtures.py
    ```

## If a script stops

- Tool platform/checksum/download error: use Linux x86_64, check connectivity
  and retry `80`. A checksum mismatch must be investigated before installation.
- Missing tool: install the existing platform prerequisites first; do not use
  sudo from Codex. `80` uses curl, Python's ZIP reader and sha256sum.
- Sign-in expired, missing/old/invalid sign-in time: run `83` again during the
  run phase. `81`, `82`, `85` and node replacement require a sign-in under
  11 hours old. Never sign in while a builder is working.
- Caller differs from bucket account: stop; use the correct AWS account. Do
  not edit the backend file to bypass the check.
- Invalid local setting/email, missing certificate email: correct the private
  settings through the existing platform setup or rerun `81` and enter a valid
  email. Existing `aws/do.env` is never overwritten.
- Missing backend: run `81`. Missing endpoint/kubeconfig: resume `82`. Wrong
  Kubernetes server: restore the dedicated AWS kubeconfig; never point it at
  the Droplet. The scripts freeze their checked file for the rest of the run.
- Not confirmed/no input: no further action was taken; plans were removed.
- NAT/address in control-plane plan: stop; the Terraform dependency graph
  needs review. Nothing in that plan was applied.
- Paid resource counts changed, deletion or replacement: show the new plan and
  costs to Aziz for a new decision. A re-run with zero paid changes proceeds;
  a partially built copy with other counts still stops for review.
- Root admin access unproven: stop, destroy the control plane with `85` on
  Aziz's yes, then ask the spec author. No nodes or NAT have been built yet.
- EBS configuration key absent from AWS's schema: stop before plan 2 is applied;
  the spec author must resolve the chart/schema mismatch. The message names
  the exact key, including its parent path. The managed add-on accepts
  `controller.env` (`AWS_REGION=ap-southeast-1`), `controller.additionalArgs`
  (`--k8s-tag-cluster-id=ooh-aws`) and `controller.extraVolumeTags`.
  The flag is registered in the driver's [v1.68.0 source](https://github.com/kubernetes-sigs/aws-ebs-csi-driver/blob/v1.68.0/pkg/driver/options.go#L116).
  Fixtures include the saved real AWS schema; the upstream Helm chart's
  `controller.region` and `controller.k8sTagClusterId` keys are not accepted
  by this managed add-on.
- No Auto Scaling group launch template: stop and inspect the group. A missing
  `eks:cluster-name=ooh-aws` tag requires Aziz's decision about extending the
  sweep to the saved `EKS_LT_ID`. This prints `FAIL` while `82` carries on to
  plan 3; Claude asks Aziz while the run continues. The running copy still
  costs USD 0.42/hour; the template itself costs nothing. Do not resume Codex
  until AWS logout.
- Missing load balancer or CNAME/HTTP failure: inspect controller readiness,
  public subnet tags, DNS records and port 80, then retry `82` or `84` as needed.
- Destroy wait timeout: inspect the named controller, pods or data disks and
  repeat `85`; its controller cleanup waits for tagged target groups and
  security groups too. Never remove finalizers by hand. `FAIL: leftover` names
  every remaining resource. Investigate before saying billing has stopped.
- Normal destroy and `--all` log out on exit, including refusals and errors.
  Sign in again before retrying. `--sweep-only` leaves the session unchanged;
  finish that AWS work block with the logout command above.
- Inventory failure: check sign-in and read permissions, then retry the sweep.
  Failed reads never count as an empty account.
- Replacement timeout: inspect node-group events, disk attachments and EBS CSI
  logs. Record the elapsed time only for a successful replacement.
- Any AWS check `FAIL`: the line identifies the failed requirement; use the
  matching AWS, Kubernetes or DNS read commands and rerun `86`. Resource
  ownership failures also print the unexpected IDs. Do not accept the stage
  until every check passes. The generic step failure means existing resources
  remain; retry the stated script or use `85` to end billing.

## Files, state and approvals

The roots are intentionally separate. `bootstrap` creates only the state bucket
and budget. Its local state is `~/.config/ooh/terraform/bootstrap.tfstate`.
`cluster` creates VPC, control plane, node, roles and managed add-ons. `addons`
reads cluster outputs through S3 remote state and creates controller roles, Helm
releases and `ooh-gp3`. S3 keys are `cluster/terraform.tfstate` and
`addons/terraform.tfstate`. Native S3 locking is enabled; no DynamoDB exists.

All local settings, plans and kubeconfigs are private. Each script uses
`umask 077`, the plan folder is mode 700 and plan files are mode 600. Plans are
removed after apply, refusal or failure. The budget recipient is sensitive in
Terraform. Never commit state, plans, backend settings or local account values.

`81` also provides shared shell functions to `82`–`86`; sourcing it does not run
bootstrap. `85` supplies the read-only inventory to `86`. Neither sources Part
B's target selector: these scripts must work before and after a node exists.
The full root README belongs to Part B. Run-phase commands use the reviewed
merged `stage-4b` worktree; after acceptance use the main clone as stated above.

The network uses two public /24 and two private /20 subnets. The node and NLB
stay in zone a so the retained-in-use EBS disks can attach after replacement.
The AWS copy's disk reclaim policy is Delete, as Aziz approved. There is no
high availability. Terraform sets the project tags; controllers tag generated
resources for inventory and cleanup. The run phase verifies EKS's own tags.
