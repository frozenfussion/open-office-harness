# Stage 4 phase 2 — The same system on AWS (EKS, built by Terraform)

Written 2026-11-14 by Claude (orchestrator). Read `00-GLOBAL-RULES.md` first; it applies in full. A stage spec may add rules, never remove them; the two exceptions asked of Aziz are in section 4, rows "Data on the AWS copy" and "Visitor addresses in the AWS access log".
**Base commit:** `main` right after this spec is merged (Aziz's yes). Aziz's answers on three items — the two exceptions in section 4 ("Data on the AWS copy", "Visitor addresses in the AWS access log") and whether one yes covers the three build prompts of `82` (section 7) — are written into section 0 **before** that merge; `stage-4b-base` is the merge commit that contains it. Before any Part starts, Claude tags it and pushes the tag from harness.
**Review:** Claude Code spec review 14 Nov 2026 (`reviews/stage-4b-spec-review`, 22 findings) re-review (`reviews/stage-4b-spec-rereview`, 17 findings) round 3 (`reviews/stage-4b-spec-rereview-2`, 11 findings) round 4 (`reviews/stage-4b-spec-rereview-3`, 6 findings) round 5 (`reviews/stage-4b-spec-rereview-4`, 5 findings) round 6 (`reviews/stage-4b-spec-rereview-5`, 4 findings) round 7 (`reviews/stage-4b-spec-rereview-6`, 3 findings) round 8 (`reviews/stage-4b-spec-rereview-7`, 1 finding) round 9 (`reviews/stage-4b-spec-rereview-8`, 1 finding) round 10 (`reviews/stage-4b-spec-rereview-9`, 3 findings) and round 11 (`reviews/stage-4b-spec-rereview-10`, 3 findings) folded in; section 16 lists each.
**Tag when accepted:** `eks-ready` (on the merged `stage-4b`). Then the AWS copy is destroyed (Aziz's yes); the code stays, so it can be rebuilt any time.

## 0. Aziz's words and decisions (Malaysia time)

- 07 Nov 16:50: "No clicking in consoles for AWS: Terraform only." State in S3 with a lock file (D024).
- 10 Nov 13:41 (D082): Stage 4 = class-ready + AWS via Terraform, tag `eks-ready`, then destroy.
- 12 Nov 17:32 (D101): "reduce my work... I'll only do authentication." Claude does all AWS work; Aziz has a root account; no long-lived root keys; every paid resource needs his yes with its cost.
- 14 Nov 15:50: "we have to keep track of billing... I don't want to go bankrupt with AWS." Stale resources removed first (done 14 Nov: two old database snapshots, one old IAM user with an active key, on his yes).
- 14 Nov 16:34 (D106): region **Singapore** (`ap-southeast-1`).
- 14 Nov 16:42 (D107): **option B** — "let's go for B, record everything, log everything ... we're going to need diagrams of how everything works and how the shift changes everything ... pros, cons". B = our own Kafka, PostgreSQL and Keycloak run inside EKS exactly as on the Droplet, from the **same Docker images**; replaces the managed MSK + RDS + S3 part of D024.
- 14 Nov 18:13: "1 yes, 2 yes, 3 yes, 4 yes" — Aziz agrees: (1) the AWS copy's own test data is deleted at destroy (section 4, "Data on the AWS copy"); (2) visitor addresses are logged on the AWS copy only, deleted with it (section 4, "Visitor addresses in the AWS access log"); (3) his one yes covers the three build prompts of `82` (section 7); (4) this spec goes to `main` and the two builders start.
- 14 Nov 16:39–16:41: the AWS copy gets its own web names (CNAME records at DigitalOcean, added by Claude on Aziz's yes); the Droplet keeps its names and stays the main system for the class.

## 1. Purpose

Prove that the class system is portable: the platform and the nine services that run on the k3s Droplet run unchanged on Amazon EKS, with everything on AWS created by Terraform and removed by Terraform. Same Docker images (code `7c721a4de601`, tag `class-start`), same manifests, a different values file — exactly as the global rules promise ("k3s now, AWS EKS later, with the same manifests and different values").

What changes between the two homes is only the ground the system stands on (the comparison table in section 13 is the source for the deck and handout diagrams):

| Layer | Droplet (stays) | AWS copy (this stage) |
|---|---|---|
| Machines | one DigitalOcean Droplet, 8 vCPU / 16 GB, made by hand | one EKS worker node `t3.xlarge` (4 vCPU / 16 GB) in a private subnet, made by Terraform |
| Kubernetes | k3s 1.36 on the Droplet | Amazon EKS 1.36 (control plane run by AWS) |
| Front door | k3s's built-in Traefik on the Droplet's IP | the same Traefik (3.7), behind an AWS Network Load Balancer (one zone, `a`) made by the AWS Load Balancer Controller |
| Disks | k3s `local-path` on the Droplet disk, reclaim Retain | EBS `gp3` volumes (encrypted) through the EBS CSI driver, StorageClass `ooh-gp3`, reclaim Delete |
| Web names | A records `harness.`, `admin.`, `auth.faysalaziz.com` → the Droplet IP | CNAME records `harness.aws.`, `admin.aws.`, `auth.aws.faysalaziz.com` → the load balancer's name |
| Network | public IP + DigitalOcean firewall (22, 80, 443) | VPC with public and private subnets, one NAT gateway, security groups; Kubernetes API reachable only from harness |
| Kafka, PostgreSQL, Keycloak, Jaeger, cert-manager | Strimzi, CloudNativePG, Keycloak operator, Jaeger, cert-manager | the same, same versions, inside EKS |
| Our nine services | ghcr.io images, tag `7c721a4de601` | the same images |
| Who runs it | Claude in Aziz's tmux window | the same; Terraform state in an S3 bucket with a lock file |

## 2. Done when (all of these)

1. `infra/terraform/aws/` passes `terraform fmt -check -recursive`, and per root `terraform init -backend=false && terraform validate` and `tflint --init && tflint` with the AWS ruleset at the versions `80` installs (Part A; no AWS sign-in needed).
2. Every changed `install/*.sh` passes `bash -n` and `shellcheck`; `kubeconform -strict` passes on `deploy/platform/` rendered by `30 --check` for both `do` and `aws` (Part B; `deploy/apps/` is rendered by the deploy scripts at apply time and is unchanged by this stage); `30 --check` renders byte-identical files to today's for `OOH_TARGET=do` (section 6.4).
3. On harness, Claude runs `install/81-aws-bootstrap.sh` and `install/82-aws-cluster.sh` in Aziz's shell window; each shows its Terraform plan and its cost line (section 4) and stops; after Aziz's yes in chat Claude types `yes`; each ends with `DONE`.
4. Claude adds the three CNAME records at DigitalOcean (Aziz's yes) and `install/84-aws-dns.sh` prints `PASS` for all three.
5. With `OOH_TARGET=aws`, the platform and app scripts in the README AWS order (section 10) each end with `DONE`; Aziz types the first admin's details (50) and, in the AWS Admin Console, the provider keys (tier 1, tier 2 and a classification entry, as on the Droplet) and gives himself the Slides grant.
6. With `OOH_TARGET=aws`: `40`, `62`, `70`, `77 7c721a4de601` and `78 7c721a4de601` print only `PASS` (and the INFO/SKIP lines those checks allow), each ending with `DONE`; `install/86-check-aws.sh` prints only `PASS` and its one INFO line (section 9).
7. **Node replacement test** (the AWS stand-in for the Droplet reboot test): Claude runs `install/86-check-aws.sh --replace-node` (Aziz's yes; the one named exception to "only Terraform changes AWS", section 4), which terminates the worker node's instance; within 25 minutes the node group has a new node and `40`, `62` and `86` pass again without anyone touching the cluster. The script prints the measured time for the instructor guide.
8. Aziz, in his browser, on `https://harness.aws.faysalaziz.com` and `https://admin.aws.faysalaziz.com`: signs in, chats on tier 1 and Auto, makes a Slides deck and downloads it, sees a trace in Audit. Each page shows a valid certificate.
9. An independent read-only audit (Claude Code, its own tmux window) of the live AWS copy against this spec finds nothing open.
10. `install/85-aws-destroy.sh` (after `eks-ready` and Aziz's yes) ends with `DONE`, the three CNAME records are removed, and `install/85-aws-destroy.sh --sweep-only` (read-only; repeatable by the audit and by Aziz at any time) finds nothing left from this stage except the Terraform state bucket and the budget (section 4). The Billing page shows the AWS copy's charges stopped.
11. `README.md` has the "AWS copy" guide (section 10); `docs/STATUS.md` says Stage 4 phase 2 is done and lists what was checked; `docs/ARCHITECTURE.md` and `contracts/storage.md` no longer say AWS is "Stage 6", and `contracts/identity.md` says the AWS copy uses the same names under `DOMAIN=aws.faysalaziz.com` (section 6.4).

## 3. Prerequisites (done 14 Nov, before this spec)

1. AWS command-line tool 2.40.3 and Terraform 1.17.2 in `~/.local/bin` on harness (no sudo). `install/80-aws-tools.sh` (Part A) repeats this exactly, so a fresh server gets the same result.
2. harness signed in with `aws login --remote` as the account's root user (short-lived credentials, refreshed every 15 minutes, session up to 12 hours; no access key exists). Default region `ap-southeast-1`. When the session ends, Claude runs `install/83-aws-login.sh` again and opens the link for Aziz.
   **Sign-in rule (review finding 3):** the cached root session (`~/.aws/login/`) is readable by every process running as `aziz`, Codex included. So: no AWS session exists while any Codex window is building or fixing (Claude runs `aws logout` before starting or resuming a Codex window and checks `aws sts get-caller-identity` fails); Claude signs in only for the run phase (section 7, "Merge, apply, deploy, check"), always through `install/83-aws-login.sh`, and runs `aws logout` at the end of every AWS work block and at the end of `85`. Codex never runs `kubectl` against EKS.
3. Account cleaned (section 0). Kubernetes 1.36, PostgreSQL 18.4 (not used: B) and three availability zones offered in Singapore; account limit 64 vCPUs for standard servers.

## 4. Decisions for this stage (fixed; versions checked 14 Nov 2026 from the AWS command line, HashiCorp's registry, the Traefik and EKS chart indexes, and AWS's pages)

| Item | Decision | Why (and the alternative, for the teaching material) |
|---|---|---|
| Region | `ap-southeast-1`, availability zones `a` and `b` for the network; the node only in `a` | D106. EBS volumes live in one zone; a single node pinned to one zone keeps its disks attachable after a replacement. Alternative: Malaysia (`ap-southeast-5`), ~10% cheaper, not enabled on the account |
| Terraform | 1.17.2; providers `hashicorp/aws` 6.73.0, `hashicorp/helm` 3.3.0, `hashicorp/kubernetes` 3.5.0, pinned exactly, with `.terraform.lock.hcl` committed | Exact versions (global rules). Builders re-check on the day and report any newer patch, never change silently |
| Terraform roots | three: `bootstrap` (state bucket + budget, local state), `cluster` (network, EKS, node group, add-ons, roles), `addons` (Load Balancer Controller, Traefik, StorageClass) | The state bucket must exist before anything can store state in it; the Helm and Kubernetes providers need a running cluster, so they live in their own root (avoids the known "provider configured from a resource that does not exist yet" problem) |
| State | S3 bucket `ooh-tfstate-<account id>-apse1`, versioning on, encryption SSE-S3, all public access blocked, `use_lockfile = true` (native S3 lock, no DynamoDB) | D024. The bucket name holds the account ID, so it is **never** written in the repo: `81` writes `~/.config/ooh/aws-backend.hcl` (mode 600) and both later roots run `terraform init -backend-config=` that file |
| `bootstrap` state | local file `~/.config/ooh/terraform/bootstrap.tfstate` (mode 600), outside the repo | A bucket cannot hold its own creation state. Small and easy to rebuild |
| Budget | AWS Budgets, monthly cost budget `ooh-aws-copy` USD 40: emails at 50%, 80%, 100% actual and 100% forecast to the address in `~/.config/ooh/aws.env` (`BUDGET_EMAIL`, never in the repo) | "I don't want to go bankrupt" (Aziz). Two budgets per account are free; the existing "Basic" USD 5 budget stays untouched. The AWS Budgets page said on 14 Nov that recipients added after 30 Sep 2026 must confirm their address (seen on the console, not yet on a documentation page: UNVERIFIED 7); the README tells Aziz to click the confirmation email. Budget emails can arrive 8–24 hours late, so the bill is also read on the Billing page at every update |
| Sign-in for Terraform and `kubectl` | the root user's `aws login` session, only during the run phase (section 3 sign-in rule); EKS `authentication_mode = "API"` and `bootstrap_cluster_creator_admin_permissions = true` | D101 (root cannot assume roles; no access keys). **UNVERIFIED 1** (section 12): that a root session works as cluster creator for `kubectl`; proven first, before the node group is created |
| Network | VPC `10.42.0.0/16`; two public subnets (`/24`, zones a and b, for the load balancer and the NAT gateway) and two private subnets (`/20`, zones a and b; the node in private-a); one NAT gateway in public-a; no IPv6 | Real-world layout: nodes have no public address. One NAT gateway, not one per zone: saves USD 0.059/hour; the copy is not highly available anyway |
| EKS | Kubernetes **1.36** (same as k3s; standard support to 2 Aug 2027); cluster name `ooh-aws`; API endpoint public **only to `143.198.221.2/32`** plus private; control-plane logging off | Same version as the Droplet. Locked endpoint: only harness can reach the API. Logging off saves CloudWatch cost |
| Worker node | one EKS managed node group `main`: `t3.xlarge`, Amazon Linux 2023 EKS-optimised image (`AL2023_x86_64_STANDARD`, release 1.36.5-20261107 or newer on the day), min 1 / desired 1 / max 1, private subnet `a` only, no SSH. A **launch template** sets the 50 GB `gp3` root disk encrypted with the AWS-managed `aws/ebs` key and `delete_on_termination = true`, IMDSv2 required with hop limit **1** (pods cannot use the node's role), and `tag_specifications` so the instance, its disk and its network interfaces carry the project tags. No extra node security group: only the EKS cluster security group, so the control plane reaches the webhooks and the kubelet (`exec`, `logs`, `port-forward`, used by `40`, `62`, `70`, `77` and `install/lib/stage-check.sh`) | Measured on the Droplet 14 Nov: our pods request 2.9 CPU and 5.1 GiB, use about 7 GiB; `t3.xlarge` gives 4 vCPU, 16 GiB and room for 58 pods (we run about 35 with EKS's own). One node keeps the shared `ooh-files` disk attachable by both the Harness and the Slides worker (the volume is single-node, as on the Droplet). Alternative: two nodes + EFS for files (more cost and parts) |
| EKS add-ons (managed, versions from `aws eks describe-addon-versions` for 1.36 on the day) | `vpc-cni` v1.22.4-eksbuild.14, `kube-proxy` v1.36.0-eksbuild.65 and `eks-pod-identity-agent` v1.4.1-eksbuild.3 **before** the node group; `coredns` v1.14.7-eksbuild.35 and `aws-ebs-csi-driver` v1.68.0-eksbuild.1 **after** it (without a node, coredns stays degraded and the create fails) | AWS's defaults for 1.36 on 14 Nov. EBS CSI gets its own role through **EKS Pod Identity** with the AWS-managed `AmazonEBSCSIDriverPolicy` (least privilege for the pod, no node-wide rights); its `extraVolumeTags` carry the project tags, `controller.additionalArgs` `--k8s-tag-cluster-id=ooh-aws` makes its volumes carry `kubernetes.io/cluster/ooh-aws=owned`, and the managed add-on sets `AWS_REGION` itself (section 17 rows 10–11), because hop limit 1 hides instance metadata from its controller |
| Load balancer | AWS Load Balancer Controller, Helm chart **3.6.3** (app v3.6.3), in `kube-system`, role through Pod Identity with the IAM policy file published at tag `v3.6.3` (copied into the repo, not fetched at apply time); Helm values `region` and `vpcId` from Terraform (it cannot read them from instance metadata with hop limit 1) and `defaultTags` = the project tags | AWS's recommended controller; the legacy in-tree one is "only receiving critical bug fixes" (AWS EKS best practices). One Network Load Balancer for the whole system |
| Front door | Traefik, Helm chart **42.4.0** (Traefik v3.7.18; the Droplet runs 3.7.15), release `traefik` in `kube-system`, IngressClass `traefik`; Service type LoadBalancer with annotations: `aws-load-balancer-type: external`, `aws-load-balancer-scheme: internet-facing`, `aws-load-balancer-nlb-target-type: ip`, `aws-load-balancer-proxy-protocol: "*"`, `aws-load-balancer-subnets: <public subnet a>` (one zone, the node's zone: no zone without a target, one public address fewer); Traefik entry points `web` (80) and `websecure` (443) with `proxyProtocol.trustedIPs` = the two public subnets only (no `forwardedHeaders.trustedIPs`: the Droplet's Traefik does not set it, and it would let pods inside the VPC forge `X-Forwarded-For`); on the AWS Traefik only, the JSON access log with `fields.defaultMode=drop` keeping only `ClientHost`, `DownstreamStatus` and `StartUTC`, and `fields.headers.defaultMode=drop` keeping only `X-Ooh-Marker` (no path, query string, host, user or token is ever logged), used by `86` item 8; Helm release `traefik` `depends_on` the controller's release | Our Ingresses say `ingressClassName: traefik` and cert-manager's HTTP-01 solver uses Traefik: keeping Traefik means **no manifest change**. Proxy protocol keeps the visitor's real address, which our trust-boundary rule needs (Traefik adds `X-Forwarded-For`). The access log is the only way to prove it without an application change (the Harness writes no access log). The builder copies every other Traefik setting from the Droplet's live k3s Traefik (read with `kubectl -n kube-system get deploy traefik -o yaml` and the k3s HelmChart), and lists each one in the report |
| Disks | StorageClass `ooh-gp3` (made in `addons`): provisioner `ebs.csi.aws.com`, `type: gp3`, `encrypted: "true"`, `volumeBindingMode: WaitForFirstConsumer`, `reclaimPolicy: Delete`, `allowVolumeExpansion: true`, tag `ooh-stage=4b` on every volume | WaitForFirstConsumer matches `local-path`, so `30`'s first-consumer step works. Delete + tags so nothing is left behind at destroy. **Group ownership:** unlike `local-path`, an EBS volume is re-owned to each mounting pod's `fsGroup`, so the one script pod in `40` that mounts `ooh-files` (and `30`'s binding pod) runs as `FILES_POD_UID` from the values file: `10001` (the apps' identity) for `aws`, unchanged `1001` for `do`, where `local-path` ignores `fsGroup` and `/files/checks` already belongs to 1001. The other `40` check pods (Kafka, PostgreSQL, tracing) are unchanged (Part B) |
| Data on the AWS copy | **Exception to "Nothing is ever deleted", for the AWS copy only, asked of Aziz with this spec:** the copy has its own empty databases, Kafka and files; they hold only check and test data and are deleted at destroy (`85`). The Droplet's data is never touched | Destroy was agreed (D082); leaving disks would keep billing. The Droplet stays the only home of real data |
| Visitor addresses in the AWS access log | **Exception to global rule "never log ... personal details", for the AWS copy only, asked of Aziz with this spec:** Traefik's access log on the AWS copy records each visitor's IP address (with only the status and time), in the pod's output only; it is deleted with the copy at destroy. The Droplet logs nothing new | The only way to prove the trust-boundary rule without an application change (review finding 1, re-review 7) |
| Web names | `DOMAIN=aws.faysalaziz.com` in `deploy/values/aws.env`; records `harness.aws`, `admin.aws`, `auth.aws` = CNAME to the load balancer's DNS name, TTL 300, made by Claude in the DigitalOcean control panel after `82` (Aziz's yes), removed after `85` | All our manifests and scripts already build names as `harness.$DOMAIN`, so no code change. DNS stays at DigitalOcean (no Terraform DigitalOcean token in the repo or on harness) |
| Certificates | cert-manager and Let's Encrypt exactly as on the Droplet (staging first, then production) | Same scripts. New names, so no rate-limit clash with the Droplet's certificates |
| Local settings | for `aws`, these files live under `~/.config/ooh/aws/`: the test-database settings files of `59`, `64`, `66`, `74`, and the Let's Encrypt email file (section 6.1 step 6). Stay where they are and are shared: the check lock `~/.config/ooh/stage-check.lock` (so only one check runs on harness at a time; the checks use fixed local ports 18080–18082), and Part A's own files `aws.env`, `aws-backend.hcl`, `terraform/bootstrap.tfstate` | The Droplet's own files are never overwritten by an AWS run (review finding 7c, re-review 12) |
| Secrets | Kubernetes Secrets made by the same scripts (`20`, `59`, `60`, `63`, `64`, `66`, `71`, `72`, `74`); EKS encrypts Kubernetes secrets at rest by default | Same as the Droplet. No AWS Secrets Manager (option B) |
| Images | the nine `ghcr.io/frozenfussion/ooh-<name>:7c721a4de601` images, pulled through the NAT gateway | "Same images" (D107) |
| Tags | Terraform `default_tags`: `project = open-office-harness`, `stage = 4b`, `managed-by = terraform`; the same three through the launch template, the controller's `defaultTags` and EBS CSI `extraVolumeTags`. Resources made by controllers also carry AWS's own tags (`elbv2.k8s.aws/cluster=ooh-aws`, `kubernetes.io/cluster/ooh-aws=owned`, `cluster.k8s.amazonaws.com/name=ooh-aws`); the sweeps search for both | Lets the destroy check and Cost Explorer find everything. Every IAM role, policy and instance profile the roots create is named `ooh-aws-*` and carries the tags, so the global IAM sweep finds them |
| Who may change AWS | only Terraform (roots above) and the controllers it installs; Claude never clicks in the AWS console to create or change a resource; reading the console (bills, checks) is allowed. Named exceptions, each in a listed script and each on Aziz's yes: `86 --replace-node` (ends the node's instance for the test) and `85`'s ordered clean-up of Kubernetes objects before `terraform destroy` | 07 Nov rule |

**Cost (Singapore, on-demand, AWS Price List API 14 Nov 2026), per hour while the copy runs:** EKS cluster 0.10 + `t3.xlarge` 0.2112 + NAT gateway 0.059 (+ 0.059 per GB through it) + Network Load Balancer 0.0252 (+ about 0.006 per capacity unit) + EBS `gp3` 110 GB at 0.096/GB-month ≈ 0.015 + two public IPv4 addresses (NAT gateway, load balancer in one zone) at 0.005 = 0.010 → **about USD 0.42 an hour, about USD 10.10 a day**, plus one-off traffic: pulling the images through the NAT gateway (about USD 0.30, and again at the node replacement test), data to the internet at USD 0.12/GB (small). **A copy forgotten and left running costs about USD 310 a month**; that is why `85` and the bill check end every AWS block. The state bucket and the budget cost almost nothing and stay after destroy. `t3` servers bill extra CPU credits only above 40% sustained CPU; the Droplet runs at about 5%. CPU room: our pods request 2.87 CPU, EKS's own about 0.6, the node offers about 3.92: about 0.4 CPU left for the rolling-update extra pod of each deploy (one at a time, as the scripts do).

## 5. Data

No schema change, no new topic, no new database. The AWS copy starts empty: `30` makes the topics and databases, `50` the first admin (Aziz types), the Admin Console the model entries and keys (Aziz types the keys; never Claude, never a file).

## 6. Interfaces

### 6.1 Target selection (Part B owns; Part A reads)

- Every install script selects its target with `OOH_TARGET` (`do` default, or `aws`). A new `install/lib/target.sh` is sourced **instead of** `deploy/values/do.env` in every script that sources it today (27 scripts, listed by `grep -l deploy/values/do.env install/*.sh install/lib/*.sh`). It:
  1. sources `deploy/values/${OOH_TARGET}.env` (stop on any other value: `STOP: OOH_TARGET must be do or aws`);
  2. sets `KUBECONFIG` to `KUBE_CONFIG` from that file (`do`: `$HOME/.kube/config`; `aws`: `$HOME/.kube/ooh-aws.config`) and exports it — **unless** a parent script already froze it (step 5 markers present with the same target: reuse that file; a different `OOH_TARGET` in a child → `STOP: child script target differs from its parent`);
  3. prints its first line: `TARGET do (Droplet, live class system)` or `TARGET aws (EKS copy)`;
  4. unless the script runs in a render-only mode (`30 --check`, which skips steps 4 and 5 and makes no cluster call), checks the cluster is the expected one before any other `kubectl` call: `do` → the API server is `https://127.0.0.1:6443` **and** a node's `spec.providerID` starts with `k3s://`; `aws` → the API server equals `EKS_ENDPOINT` in `~/.config/ooh/aws.env` (written by `82`) **and** a node's `spec.providerID` starts with `aws:///ap-southeast-1a/`. Mismatch → `STOP: this shell points at <found>, not the <target> cluster; nothing was changed`; no node at all → `STOP: no node is registered yet in the <target> cluster; wait and retry`;
  5. then freezes the choice for the whole run: writes `kubectl config view --minify --flatten` to a private temporary file (mode 600) and exports `KUBECONFIG` to it plus `OOH_FROZEN_KUBECONFIG=<file>` and `OOH_FROZEN_TARGET=<target>`, so a context switch elsewhere during a long run (or `aws eks update-kubeconfig` merging into `~/.kube/config`) cannot redirect this script, its child scripts (`30` → `35`) or its port-forwards. Only the script that made the file removes it on exit;
  6. sets `OOH_LOCAL` = `~/.config/ooh` for `do` and `~/.config/ooh/aws` for `aws`; every script that reads or writes a local settings file (`~/.config/ooh/do.env` for the Let's Encrypt email, the test-database files of `59`, `64`, `66`, `74`) uses `$OOH_LOCAL` instead of the fixed folder. For `aws`, `OOH_LOCAL/do.env` is a copy of the Droplet's (only `LETSENCRYPT_EMAIL`), made by `81`. In render-only mode a missing local settings file is replaced by a placeholder email, so `30 --check` runs for both targets during Part B.
- **`target.sh` is for the platform and app scripts (00–79) only.** Part A's scripts (80–86) do not source it: they set `KUBECONFIG=$HOME/.kube/ooh-aws.config` themselves and check the API server against `EKS_ENDPOINT` only (no node check), because they run before the node exists, while it is replaced, and after it is gone.
- **Safety rule:** a Droplet script can never reach EKS by accident, and the reverse; the checks above run before the first `kubectl` call. Tested both ways with fake settings (section 7).
- `30 --check` prints one `sha256  <path relative to the render root, e.g. deploy/platform/kafka/kafka.yaml>` line per rendered file, sorted by path, so Part B can show the `do` output before and after is identical (the render folder is removed on exit). The renderer refuses any token of the form `${[A-Z][A-Z0-9_]*}` that is not in its list; lower-case Keycloak placeholders (`${username}`, `${email}`, `${firstName}`, `${lastName}` in `realm-ooh.yaml`) pass through unchanged, as today.
- Messages: Part B may change any `STOP`/`FAIL` text that names `deploy/values/do.env`, `local-path`, k3s or `PUBLIC_IP` so it names the target's values file and storage; `aws.env` defines no `PUBLIC_IP`, so no line may expand it for `aws` (30:185 today).
- `deploy/values/aws.env` (repo, no secrets, no account ID): `DOMAIN=aws.faysalaziz.com`, `PLATFORM_NAMESPACE=ooh-platform`, `APPS_NAMESPACE=ooh-apps`, `KAFKA_STORAGE=20Gi`, `POSTGRES_STORAGE=20Gi`, `FILES_STORAGE=20Gi`, `STORAGE_CLASS=ooh-gp3`, `RETAIN_VOLUMES=false`, `FILES_POD_UID=10001`, `KUBE_CONFIG=$HOME/.kube/ooh-aws.config`, `EXPECTED_NODES=1`. `deploy/values/do.env` gains `STORAGE_CLASS=local-path`, `RETAIN_VOLUMES=true`, `FILES_POD_UID=1001`, `KUBE_CONFIG=$HOME/.kube/config`, `EXPECTED_NODES=1` and keeps `PUBLIC_IP`.

### 6.2 Local settings written by Part A's scripts (never in the repo)

`~/.config/ooh/aws.env` (mode 600): `AWS_REGION=ap-southeast-1`, `EKS_CLUSTER_NAME=ooh-aws`, `EKS_ENDPOINT=<from Terraform output>`, `LB_HOSTNAME=<the Traefik Service's load balancer name, from 82 after addons>`, `BUDGET_EMAIL=<typed once by Aziz when 81 first runs; not a secret, but personal, so never in the repo>`. `AWS_SIGNIN_AT=<UTC, written by 83>`, `EKS_LT_ID=<the node group's launch template ID, written by 82>`. `~/.config/ooh/aws-backend.hcl` (mode 600): bucket, key, region, `use_lockfile = true`. `~/.config/ooh/aws/` (mode 700) and `~/.config/ooh/aws/do.env` (mode 600) holding only `LETSENCRYPT_EMAIL`, copied by `81` from `~/.config/ooh/do.env`, never overwritten. `~/.kube/ooh-aws.config` (mode 600) from `aws eks update-kubeconfig --name ooh-aws --kubeconfig ~/.kube/ooh-aws.config`.

### 6.3 What Part B's scripts read from Part A

Only `EKS_ENDPOINT`, `EKS_CLUSTER_NAME` and `LB_HOSTNAME` from `~/.config/ooh/aws.env`. Values that pass between Terraform roots (`vpc_id`, `public_subnet_a_id`, cluster name and endpoint) go from `cluster` to `addons` through `terraform_remote_state` on the same bucket. The load balancer's name is not a Terraform output (a data source would be read before Traefik exists): `82` waits with `kubectl -n kube-system wait --for=jsonpath='{.status.loadBalancer.ingress[0].hostname}' service/traefik --timeout=600s` and writes `LB_HOSTNAME` itself.

### 6.4 Platform manifests and Droplet-only checks (Part B)

- `deploy/platform/postgres/cluster.yaml` `storageClass`, `deploy/platform/kafka/kafka.yaml` `class` and `deploy/platform/storage/files-pvc.yaml` `storageClassName` become `${STORAGE_CLASS}`; `30` adds `STORAGE_CLASS` (and uses `FILES_POD_UID`) as tokens it renders (see 6.1 for unknown tokens). For `do` the rendered output must equal today's byte for byte (Part B proves it with a diff in its report).
- `30`: the Retain patch runs only when `RETAIN_VOLUMES=true`; the first-consumer binding pod runs as `FILES_POD_UID` (section 4, Disks).
- `40`: the volume check expects `STORAGE_CLASS` and, when `RETAIN_VOLUMES=true`, Retain; when false, Delete; only the check pod that mounts `ooh-files` runs as `FILES_POD_UID`; the other check pods are unchanged. Everything else in `40` unchanged.
- `00-check-server.sh`: for `aws`, instead of "resolves to `PUBLIC_IP`" it checks each name is a CNAME to `LB_HOSTNAME`; instead of "k3s node Ready" it checks `EXPECTED_NODES` Ready nodes; instead of the two requests to `127.0.0.1` (the Droplet's own Traefik) it requests `http://$LB_HOSTNAME/` and `https://$LB_HOSTNAME/` (`--insecure`, any HTTP status); messages name the target; the Traefik check stays (`kube-system`, label `app.kubernetes.io/name=traefik`: the Helm chart uses the same label — the builder confirms).
- `01-server-setup.sh` and `50-first-admin.sh` behaviour unchanged (50 only gains the target line).
- `docs/ARCHITECTURE.md` and `contracts/storage.md`: replace "Stage 6" with "Stage 4 phase 2" and describe the AWS copy in one paragraph (same manifests, EBS volume for files, destroyed after the check). `contracts/identity.md`: one sentence that the AWS copy uses the same names under `DOMAIN=aws.faysalaziz.com` (issuer `https://auth.aws.faysalaziz.com/realms/ooh`). No other change to contracts.

## 7. Parts

Two Codex windows at the same time, each in its own worktree from `stage-4b-base`. **Rule: Part A changes no file Part B lists, and the reverse.** Nobody changes the files in section 11.

### Part A — Terraform and the AWS-only scripts (branch `stage-4b-part-a`, Codex A, window `codex-a`)

Files (only these):
```
infra/terraform/aws/README.md
infra/terraform/aws/bootstrap/**          (versions.tf, main.tf, variables.tf, outputs.tf, .terraform.lock.hcl)
infra/terraform/aws/cluster/**            (the same files + vpc.tf, eks.tf, nodes.tf, addons.tf, iam.tf)
infra/terraform/aws/addons/**             (the same files + lbc.tf, traefik.tf, storage.tf, policies/aws-load-balancer-controller-v3.6.3.json)
install/80-aws-tools.sh                   (AWS tool 2.40.3 + Terraform 1.17.2 + tflint and tflint-ruleset-aws at exact versions read on the day, into ~/.local, checksums checked, no sudo)
infra/terraform/aws/*/.tflint.hcl
install/81-aws-bootstrap.sh               (bootstrap root: init, saved plan, cost line, the script's own yes prompt, apply of the saved plan; writes aws-backend.hcl and aws.env; makes ~/.config/ooh/aws/ and its do.env, section 6.2)
install/82-aws-cluster.sh                 (in three saved plans, each shown with its cost line, confirmed at the script's own yes prompt, then applied: (1) `-target` the EKS cluster, its role and its access settings only (Terraform also pulls in the VPC and subnets it needs; the NAT gateway, its address and the private routes must not be dependencies of the cluster, and `82` stops if plan (1) contains `aws_nat_gateway` or `aws_eip`; plan (1)'s cost line lists every resource it shows), then `82` writes `EKS_ENDPOINT` to `aws.env` and makes `~/.kube/ooh-aws.config`, and with the root session runs `kubectl get --raw /readyz`, `kubectl auth can-i '*' '*' --all-namespaces` = `yes`, `kubectl get namespaces` succeeds, and `aws eks list-access-entries --cluster-name ooh-aws` is printed to the terminal only, with the account ID replaced by `<account>` (never written to a file) (`/readyz` alone proves nothing: every signed-in identity may read it) (UNVERIFIED 1); (2) the rest of `cluster`; (3) `addons`, whose cost line also names what the plan cannot show: the Network Load Balancer and its public address, made by the controller (about USD 0.030/hour). Before plan (1) it prints the total from a price table fixed in the script (the section 4 cost line: about USD 0.42/hour, USD 10.10/day), since plans (2) and (3) cannot be made before plan (1) is applied. If Aziz agrees (section 0), his one yes in chat covers `82`'s three prompts, but at each later prompt `82` reads `terraform show -json <plan>` and counts, per paid type (`aws_nat_gateway`, `aws_eip`, `aws_instance`, `aws_eks_node_group`, `aws_lb`, `aws_ebs_volume`, `aws_eks_cluster`), the `resource_changes` whose `change.actions` contain `create`; expected creates: plan (2) exactly one `aws_nat_gateway`, one `aws_eip` and one `aws_eks_node_group` and no other paid type; plan (3) no paid type; any other count, or any `delete` of a paid type (a replace included), stops for a new yes; `82` stopping at UNVERIFIED 1 also needs a new yes. After the node group is up, prints to the terminal the tag keys and values of the node group's Auto Scaling group and of the launch template it uses, read from `LaunchTemplate`, or else from `MixedInstancesPolicy.LaunchTemplate.LaunchTemplateSpecification`, of `aws autoscaling describe-auto-scaling-groups` (if neither names one: `FAIL: no launch template found on the Auto Scaling group` and stop), with the account ID replaced by `<account>`, and saves that launch template's ID to `aws.env` as `EKS_LT_ID` (section 8 step 6). Updates aws.env with `LB_HOSTNAME`; waits for the node and the load balancer name; prints the three CNAME records to add)
install/83-aws-login.sh                   (runs `aws login --remote`, prints the link for Claude to open, then records `AWS_SIGNIN_AT=<UTC>` in aws.env; Claude always signs in through it)
install/84-aws-dns.sh                     (each name resolves as a CNAME to LB_HOSTNAME; HTTP on port 80 reaches Traefik)
install/85-aws-destroy.sh                 (section 8; `--sweep-only` is read-only)
install/86-check-aws.sh                   (section 9; `--replace-node` for Done-when 7)
.gitignore                                (add .terraform/, *.tfstate*, *.tfplan; nothing else)
```
Rules: no account ID, email, IP of anyone but harness (`143.198.221.2`, already public in the repo), or key in any file; every resource tagged (section 4); `prevent_destroy` on nothing (the copy must be destroyable); every build runs `terraform plan -out ~/.cache/ooh/<root>[-<n>].tfplan`, shows it with its cost line, asks in its own words `Type yes to build <what> (about USD x/hour)` (any other answer: stop and delete the plan file), then `terraform apply <saved plan>` (which never prompts), so what Aziz approved is exactly what is built; each Part A script sets `umask 077` before its first `terraform` call and makes `~/.cache/ooh/` with `install -d -m 700`, so each plan file is mode 600 (plans hold state and variables in clear text); a plan file is deleted after it is applied or refused; each script refuses to run when `aws sts get-caller-identity` fails (`STOP: AWS sign-in expired; run install/83-aws-login.sh`) or when the caller's account differs from the bucket's account; `85` ends with `aws logout`. Each script prints the resources it will create with their hourly price (section 4 table) before its yes prompt.

Part A done when: section 2 item 1 passes; its report states which tags it expects on EKS's Auto Scaling group and launch template, with the documentation source, or "not documented" (section 8 step 6); Part A confirms against Traefik chart 42.4.0's `values.yaml` and the EBS CSI add-on's configuration schema the exact keys it uses, and reports them; `bash -n` and `shellcheck` clean for its scripts; per root, `terraform init -backend=false && terraform validate` and `tflint --init && tflint` pass (no AWS sign-in needed; Codex never has one). The real-account plans are first run by `81` and `82` at the start of the run phase (UNVERIFIED 9).

### Part B — Target selection and portable manifests (branch `stage-4b-part-b`, Codex B, window `codex-b`)

Files (only these):
```
install/lib/target.sh                      (new, section 6.1)
install/00-check-server.sh ... install/79-demo.sh   (only the 27 files that source do.env today, every install script except 01: the sourcing line (two forms exist: `source "$ROOT/deploy/values/do.env"` and, in 40, 77, 78, 79, `source deploy/values/do.env`), the `$OOH_LOCAL` paths, the messages in 6.1, and the changes in 6.4 for 00, 30, 40)
deploy/values/do.env                       (adds four lines, 6.1)
deploy/values/aws.env                      (new)
deploy/platform/postgres/cluster.yaml
deploy/platform/kafka/kafka.yaml
deploy/platform/storage/files-pvc.yaml
docs/ARCHITECTURE.md
contracts/storage.md
contracts/identity.md                      (one sentence, 6.4)
README.md                                  (section 10)
```
Part B done when: section 2 item 2 passes (`30 --check` makes no cluster call, for both targets, with a placeholder email when a local settings file is missing); the `sha256` lines of `OOH_TARGET=do install/30-platform-apply.sh --check` equal those of today's renderer (today's lines are taken first with a temporary copy of the old `30` that prints them; the old script itself is not changed in the repo); a test with a temporary `HOME` holding fake settings proves the safety rule both ways without touching any cluster (a `do` kubeconfig whose server is `https://example.invalid` → STOP; an `aws.env` naming a different endpoint than the kubeconfig → STOP; a `do` kubeconfig on `127.0.0.1:6443` whose node is not `k3s://` cannot be faked here, so that branch is proven live on the Droplet, where it must pass); then, **on the Droplet**, `40`, `62`, `70`, `77 7c721a4de601` and `78 7c721a4de601` still pass and the Droplet's test-settings files and its `/files/checks` folder are unchanged (Claude runs them; paid calls as before). `install/lib/stage-check.sh` is not changed (its shared lock stays, section 4).

### Merge, apply, deploy, check

Every agent runs as its visible program in a titled tile of the tmux window `work` (Aziz, 14 Nov 16:57), and Claude sends Aziz an update every few minutes. No AWS session exists while Codex works (section 3). Claude Code reviews each Part (section 8 of the global rules) until "No findings". Codex merges both into `stage-4b` from `stage-4b-base` and reruns every check on a clean worktree. Then Claude runs, in Aziz's shell window: `81` (Aziz's yes) → `82` (Aziz's yes) → DNS records (Aziz's yes) → `84` → the README AWS order → checks → node replacement test (Aziz's yes) → audit → Aziz's browser test → "accepted" → merge to `main` and tag `eks-ready` (Aziz's yes) → `85` (Aziz's yes) → sweep → records removed.

## 8. `install/85-aws-destroy.sh` (Part A)

Order (each step waits and checks; any failure stops with what is left and how to retry; it can be re-run):
1. Refuses unless the sign-in works, is less than 11 hours old, and the caller is the expected account. Each later step decides from **Terraform state**, so a re-run resumes where it stopped: steps 3 and 4 run only while `terraform state list` in `addons` is not empty (step 3 also needs the node group to exist, else it is skipped with a note); step 5 runs whenever the `cluster` state is not empty, whether or not the EKS cluster still exists. The kubeconfig (pointing at `EKS_ENDPOINT`, Part A's own check, 6.1) is needed only when step 3 or 4 will run.
2. Saves `terraform plan -destroy -out ~/.cache/ooh/<root>-destroy.tfplan` for `addons` and for `cluster` (only for roots whose state is not empty), shows both with the EBS volumes and the load balancer that step 3 removes and the hourly cost that stops, and asks once in its own words: `Type yes to destroy the AWS copy`. Steps 4 and 5 run `terraform apply <saved plan>` with no new prompt; a saved plan refused as stale on a re-run is made again and asked again.
3. Deletes, in this order, waiting for each: the Traefik Service (the controller, still running, removes the Network Load Balancer, its target groups and the security groups it made; wait until no load balancer tagged `elbv2.k8s.aws/cluster=ooh-aws` remains); the Deployments in `ooh-apps`; the KafkaTopic and KafkaUser objects (while the Strimzi entity operator still runs to clear their finalizers), then the Kafka, the PostgreSQL Cluster and the Keycloak objects; then deletes (with `--ignore-not-found`) every pod without an owner reference in `ooh-apps` and `ooh-platform` (left-over check pods of `30`, `40`, `77`, `78`, `79` whose exit trap did not run), then waits until no pod that mounts a PVC and is not in phase `Succeeded` or `Failed` remains there (10 minutes max); then every PVC; then the namespaces `ooh-apps` and `ooh-platform` with `--wait=false`. Every delete uses `--ignore-not-found` (a re-run after a partial step must not stop). It waits on the EBS volumes, not on the namespaces: until no volume remains that is tagged `ooh-stage=4b`, or tagged both `kubernetes.io/cluster/ooh-aws=owned` and `ebs.csi.aws.com/cluster=true` (10 minutes max). The node's own root disk carries neither tag combination, so it is not waited on; it goes with the node in step 5.
4. Applies the saved destroy plan of `addons` (Traefik first: its release `depends_on` the controller's, so the controller goes last).
5. Applies the saved destroy plan of `cluster`.
6. Sweep with the AWS tool, **all enabled regions** plus global IAM: no EC2 instance, EBS volume, load balancer, target group, NAT gateway, Elastic IP, network interface, security group, EC2 launch template, VPC or CloudWatch log group (`/aws/eks/ooh-aws/*`) carrying `stage=4b`, `ooh-stage=4b`, `elbv2.k8s.aws/cluster=ooh-aws`, `kubernetes.io/cluster/ooh-aws=owned`, `cluster.k8s.amazonaws.com/name=ooh-aws` or `eks:cluster-name=ooh-aws` (searched for every resource type, so EKS's own `eks-<uuid>` launch template is found too; Part A writes in its report which tags it expects there, with the documentation source, or "not documented"; in the run phase, after the node group is up, `82` prints to the terminal the tag keys and values of the node group's Auto Scaling group and of the launch template it uses (read from `LaunchTemplate`, or else from `MixedInstancesPolicy.LaunchTemplate.LaunchTemplateSpecification`, of `aws autoscaling describe-auto-scaling-groups`; if neither names one, `82` prints `FAIL: no launch template found on the Auto Scaling group` and stops) (account ID replaced by `<account>`), Claude records them in `docs/STATUS.md` (public repo, so the masking must be exact), and if `eks:cluster-name=ooh-aws` is not on that launch template, Claude asks Aziz one question, saying that the copy keeps costing about USD 0.42/hour meanwhile and that a launch template bills nothing. Proposal: `85` step 6 also checks that the launch template `EKS_LT_ID` (saved by `82`, so it survives a re-run) no longer exists. If Aziz says yes, Claude logs out of AWS (section 3), Codex makes the change on `stage-4b-part-a`, Claude Code reviews it until "No findings", and Codex merges it into `stage-4b` again before `85` runs. If Aziz says no, the sweep stays as written and the gap is recorded in `docs/STATUS.md`), or named for `ooh-aws`; per enabled region also: any EKS cluster named `ooh-aws` (`aws eks list-clusters`; one in state `DELETING` is waited on for up to 10 minutes), Auto Scaling groups tagged `eks:cluster-name=ooh-aws` or `kubernetes.io/cluster/ooh-aws=owned`, and subnets, route tables and internet gateways tagged `stage=4b`; globally: no IAM role, policy or instance profile named for `ooh-aws`; no customer-managed KMS key made by this stage → `PASS`, else `FAIL` with each leftover's ID. An EC2 instance in state `terminated` and a NAT gateway in state `deleted` count as gone (they bill nothing; AWS removes the entry by itself in about an hour); an instance in `shutting-down`, a NAT gateway in `deleting` and a volume in `deleting` are waited on for up to 10 minutes, then counted as left over. The same sweep runs in `86` item 11.
`--sweep-only` runs step 6 alone (read-only; needs only the sign-in): Done-when 10 and the audit use it.
7. Keeps `bootstrap` (state bucket and budget) unless run with `--all`, which also empties and deletes the bucket and the budget (Aziz's separate yes).
8. Removes `~/.kube/ooh-aws.config` and the `EKS_ENDPOINT`/`LB_HOSTNAME` lines of `aws.env`; prints the three CNAME records for Claude to remove at DigitalOcean; deletes any plan file left in `~/.cache/ooh/`; runs `aws logout`; `DONE`.

## 9. `install/86-check-aws.sh` (Part A), one `PASS`/`FAIL` line each, then `DONE`

Read-only, except the lock object item 9's plan creates and removes, and `--replace-node` (the section 4 exception: ends the node's instance, waits for the replacement and until every pod with a volume is Running again, then checks the old root disk is gone: no volume in state `available` tagged `stage=4b` **without** `ooh-stage=4b`). 1) caller is the expected account; 2) cluster `ooh-aws` ACTIVE on 1.36, endpoint public only to `143.198.221.2/32`, private access on; 3) exactly one node Ready, `t3.xlarge`, in private subnet `a`, no public IP; 4) the five add-ons ACTIVE; 5) the Load Balancer Controller and Traefik Ready; the Traefik Service has exactly one internet-facing Network Load Balancer with proxy protocol on; 6) StorageClass `ooh-gp3` as in section 4; every bound volume uses it, encrypted, tagged; 7) the three names resolve as CNAMEs to `LB_HOSTNAME`; 8) the visitor's real address reaches the system: a request from harness to `https://harness.aws.faysalaziz.com/ooh-address-check-<uuid>` (a 404 is fine) with header `X-Ooh-Marker: <uuid>`; the matching line in Traefik's JSON access log has `ClientHost` = `143.198.221.2`, not a VPC address — **UNVERIFIED 3** until it passes; 9) state bucket: versioning on, encryption on, public access blocked, `~/.config/ooh/aws-backend.hcl` has `use_lockfile = true`, and `terraform plan -lock-timeout=0s` on `cluster` succeeds (no stale lock left from an earlier run); 10) budget `ooh-aws-copy` exists with the four notifications; 11) the section 8 sweep, inverted: every resource carrying this stage's tags is in `ap-southeast-1` and belongs to the running copy, meaning any one of: (a) its ID or ARN is in `terraform state` of `cluster` or `addons`; (b) an EBS volume that is a PV's `volumeHandle` or the node's root disk; (c) tagged `elbv2.k8s.aws/cluster=ooh-aws` and part of the Traefik Service's load balancer; (d) a network interface attached to the node, the NAT gateway, the load balancer or the EKS control plane, or tagged `cluster.k8s.amazonaws.com/name=ooh-aws`; (e) the security group tagged `aws:eks:cluster-name=ooh-aws`; (f) the Auto Scaling group named by the node group (`aws_eks_node_group.main.resources[0].autoscaling_groups[0].name`), an EC2 instance in it, or the launch template it uses (read from `LaunchTemplate`, or else from `MixedInstancesPolicy.LaunchTemplate.LaunchTemplateSpecification`, of `aws autoscaling describe-auto-scaling-groups`; if neither names one, item 11 prints `FAIL: no launch template found on the Auto Scaling group` and `86` goes on to item 12). The `terminated`/`deleted` states count as gone, as in section 8 step 6. IAM resources (global) are checked by rule (a) only and are exempt from "in `ap-southeast-1`". Anything else → `FAIL` with its ID; 12) the nine Deployments run the `7c721a4de601` images; 13) no Kubernetes Service other than Traefik's is type LoadBalancer, and no Ingress points at the Model Gateway (same rule as `70`); 14) INFO (not a check): reminds that the budget email must be confirmed in Aziz's inbox.

## 10. README "AWS copy" guide (Part B), after the Stage 4 guide, each step with where it runs, which password, what it does, the good result

1. What the AWS copy is (two lines), the cost per hour and per day (section 4), and that it is destroyed after the check.
2. Tools and sign-in: `install/80-aws-tools.sh`; `install/83-aws-login.sh` (Aziz approves in the browser and types the code; Claude never handles the code); `aws logout` at the end of every AWS block, and never a session while Codex works.
3. `install/81-aws-bootstrap.sh` (asks for the budget email the first time; Aziz clicks the AWS confirmation email at once, or no budget email ever arrives).
4. `install/82-aws-cluster.sh` (about 20 minutes; what "waiting" looks like).
5. The three CNAME records at DigitalOcean (exact names, type, value from `82`, TTL 300), then `install/84-aws-dns.sh`.
6. Platform and apps with `OOH_TARGET=aws`, in this order: `00`, `10`, `20`, `30`, `35`, `40`, `50` (Aziz types), `59`, `60`, `63`, `71`, `61`, `64`, `65`, `66`, `67`, `68`, `69`, `72`, `73`, `74`, `75` (every deploy script with `7c721a4de601`); then in the AWS Admin Console (Aziz): models and keys (tier 1, tier 2, classification) and his Slides grant; then `62`, `70`, `77 7c721a4de601`, `78 7c721a4de601`, `86`. The builder confirms the whole order against the Stage 0–4 guides, including where `35` runs and whether a second `35` is needed after `67` on a fresh install (the Stage 2 guide runs it after the Control Centre and Harness are Ready), and corrects it in its report if a dependency differs.
7. Everyday: `export OOH_TARGET=aws` and why every script then refuses the Droplet; how to see pods, logs, the bill.
8. Node replacement test (`86 --replace-node`), with the measured time.
9. Destroy: `85`, removing the records, checking the bill.
10. Every new `STOP:` and `FAIL` line and what to do.

## 11. Files that already exist (spec author's; Codex does not change them)

`AGENTS.md`, `CLAUDE.md`, `LICENSE`, `docs/specs/*`, every service, app, worker, consumer, contract (except the documentation sentences Part B makes in `contracts/storage.md` and `contracts/identity.md`, 6.4) and Dockerfile, every `deploy/apps/**` and `deploy/platform/**` file not listed in Part B, every workflow. **No application code changes in this stage.** If a builder believes one must change, it stops and asks Aziz with the reason.

## 12. UNVERIFIED (each is proven before the step that depends on it; the script stops with a clear message if wrong)

1. **Root as EKS cluster creator.** AWS's access-entry page names IAM users and roles only. `82` applies the cluster first (control plane only, about USD 0.10/hour), then proves full rights with the root session (`can-i '*' '*'` = yes and `get namespaces`, section 7) **before** creating the node group. If refused: stop, destroy the cluster, and the spec author decides (the fallback is an IAM role for Terraform and `kubectl`, which needs a different sign-in; not chosen in advance).
2. Traefik chart 42.4.0's labels and IngressClass match k3s's (`app.kubernetes.io/name=traefik`, IngressClass `traefik`), so `00`, `40` and cert-manager's solver work unchanged.
3. Proxy protocol from the Network Load Balancer to Traefik keeps the visitor's address (section 9 item 8, proved in Traefik's access log). If not, the trust-boundary rule is not met on AWS and the stage is not accepted.
4. Strimzi 1.3.1, CloudNativePG 1.30.0, the Keycloak operator 26.8.2 and cert-manager 1.21.3 install on EKS 1.36 from the same URLs (`10`). Their documented Kubernetes ranges include 1.36 (Stage 0 section 4).
5. The `aws login` session lasts the whole apply (`82` up to about 25 minutes). No AWS command shows when a session ends (and the cache files are rewritten at every 15-minute refresh), so `83` records the sign-in time; `81`, `82`, `85` and `86 --replace-node` refuse to start when `AWS_SIGNIN_AT` is missing or more than 11 hours old; otherwise the `STOP: AWS sign-in expired` path applies.
6. Image pulls of about 5 GB through the NAT gateway finish within the scripts' current rollout waits (up to 10 minutes per Deployment).
7. The Budgets email-confirmation rule (section 4) as shown on the AWS console on 14 Nov.
8. Traefik chart 42.4.0 values for the access log (`logs.access.format=json`, `logs.access.fields.defaultMode`, `logs.access.fields.names`, `logs.access.fields.headers.defaultMode`, `logs.access.fields.headers.names`) and for proxy protocol; Part A confirms them against the chart's `values.yaml` at that version and reports.
9. Terraform 1.17.2's AWS provider and its S3 backend accept the `aws login` session. `81` proves the provider with `terraform plan` (creates nothing); `82` runs `terraform init` against the bucket before its first plan. Fallback, still without access keys: a profile with `credential_process = aws configure export-credentials --format process`.
10. The EBS CSI controller finds its region with hop limit 1: passes when the ebs-plugin controller log shows `Region provided via AWS_REGION environment variable` with `region=ap-southeast-1` (the managed add-on sets AWS_REGION itself), and AWS's add-on schema contains `controller.additionalArgs` and `controller.extraVolumeTags` (checked by `82` before plan (2); section 17 rows 10–11).

## 13. Comparison for the teaching material (filled in by the builders' reports and the audit; Claude turns it into the deck 10 diagrams and handout 07)

For each layer in section 1's table: what we changed, why, what it costs, what got better, what got worse. Already known: **better** — the control plane and node replacement are AWS's job; disks and the load balancer are made on demand by Kubernetes; everything is created and destroyed by Terraform in about 30 minutes; the API is reachable only from harness; **worse** — about USD 10 a day against the Droplet's flat price; more moving parts (VPC, NAT, controller, roles); we still run Kafka, PostgreSQL and Keycloak ourselves (patching and backups stay ours — option A would hand them to AWS at the cost of code changes); one node and one zone, so no high availability (same as the Droplet); the root sign-in on harness is a powerful credential on an internet-facing server for as long as it lasts, which is why it exists only during AWS work blocks (section 3).

## 14. Pre-mortem

| Step | Failure | How it shows | Action |
|---|---|---|---|
| Any script | sign-in expired | `STOP: AWS sign-in expired` | Claude runs `install/83-aws-login.sh`, opens the link; Aziz approves and types the code |
| `82` cluster | root not accepted or not admin | `kubectl` "Unauthorized" or "Forbidden", or `can-i` = no | UNVERIFIED 1: stop, destroy, spec author decides |
| `82` nodes | node group fails to join | node group `CREATE_FAILED` | node role policies and the private subnet's route to the NAT gateway |
| `82` addons | no load balancer name after 10 minutes | Traefik Service `<pending>` | controller logs: subnet tags `kubernetes.io/role/elb=1` on public subnets, controller role |
| `30` | volumes stay Pending | PVC `Pending` | EBS CSI add-on Ready, its Pod Identity role, StorageClass name, the controller's log ("could not get region": the add-on's region setting) |
| `30` | certificates pending | `certificate pending` | CNAME records, port 80 through the load balancer, proxy protocol on both sides |
| Any app | `ImagePullBackOff` | pod status | NAT gateway route; the images are public |
| Pods | `Pending` for CPU or memory | `kubectl describe pod` | measured: 2.87 CPU of ours + about 0.6 of EKS's own on about 3.92; a rolling update needs about 0.1–0.5 more. Deploy one script at a time; if still Pending, the spec author decides on `t3.2xlarge` (USD 0.42/hour, shown first) |
| Checks | Slides or downloads fail after `40` | `78` FAIL on Slides | the check pod's group must be 10001 (section 4, Disks) |
| `85` | VPC will not delete | `DependencyViolation` | a leftover load balancer, security group or network interface: the sweep names it; Claude removes it by its ID with the AWS tool (Aziz's yes), then re-runs `85`, which resumes at step 5 |
| Bill | higher than section 4 | budget email or Billing page | `86` and the tag sweep find the extra resource |

## 15. Out of scope

Managed Kafka (MSK), managed PostgreSQL (RDS), S3 for files (option A, D107), high availability (more nodes or zones), autoscaling, backups of the AWS copy, Route 53, AWS Secrets Manager, CloudWatch dashboards, any change to application code, contracts (except the documentation sentences in 6.4) or images, moving the class off the Droplet.

## 16. Spec review findings and what changed (Claude Code, 14 Nov 2026, `reviews/stage-4b-spec-review`)

| # | Severity | Finding | Change |
|---|---|---|---|
| 1 | HIGH | The real-address check asked for a Harness log the Harness never writes, on a route that does not exist | Proved in Traefik's JSON access log with a marker header (sections 4, 9, 12) |
| 2 | HIGH | `00` would test the Droplet's own Traefik on `127.0.0.1` while claiming AWS | `00` requests the load balancer's name for `aws` (6.4) |
| 3 | HIGH | The root session is readable by Codex (same Unix user) | No AWS session while Codex works; `aws logout` after every AWS block (section 3) |
| 4 | HIGH | On EBS, check pods would re-own the shared file disk to group 1001 | Script pods mounting `ooh-files` use 10001 (sections 4, 6.4) |
| 5 | MEDIUM | AWS order ran `61` before `63` | Order fixed (section 10) |
| 6 | MEDIUM | Part B could not run its own checks | `30 --check` skips cluster calls; kubeconform on `deploy/platform`; safety rule tested with fake settings (sections 2, 7) |
| 7 | MEDIUM | Holes in the safety rule | Frozen kubeconfig per run, node provider check, separate local settings folder, a TARGET first line (6.1) |
| 8 | MEDIUM | Destroy could leave the load balancer, security groups, volumes, log groups, IAM | Ordered clean-up, `depends_on`, all-region + IAM sweep, controller tags (sections 4, 8) |
| 9 | MEDIUM | Launch template, hop limit, security groups and add-on order missing | Added (section 4) |
| 10 | MEDIUM | Load balancer in two zones, target in one | Load balancer in public subnet `a` only (section 4) |
| 11 | MEDIUM | tflint not installed or pinned | `80` installs it; `.tflint.hcl` files (sections 2, 7) |
| 12 | LOW | `lb_hostname` output read before Traefik exists | `82` waits for it with `kubectl` (6.3) |
| 13 | LOW | Messages naming do.env, local-path, k3s, `PUBLIC_IP` | Part B may change them (6.1) |
| 14 | LOW | Node replacement outside "only Terraform"; 15 minutes tight | Named exception in `86 --replace-node`; 25 minutes, measured (sections 2, 4) |
| 15 | LOW | Slides grant missing | Added (sections 2, 10) |
| 16 | LOW | Data exception had no recorded answer | Placeholder in section 0; Aziz's yes written before `stage-4b-base` |
| 17 | LOW | `forwardedHeaders.trustedIPs` added trust nobody asked for | Dropped; proxy protocol trusted only from the public subnets (section 4) |
| 18 | LOW | Cost: arithmetic, missing items, forgotten-copy cost, CPU room | Corrected (section 4, 14) |
| 19 | LOW | No way to know when the sign-in ends | Sign-in time recorded; 11-hour limit (section 12) |
| 20 | LOW | Budget email confirmation not checked | README step and INFO line; UNVERIFIED 7 |
| 21 | LOW | `contracts/identity.md` names the Droplet's issuer | One sentence for the AWS names (6.4) |
| 22 | LOW | Final sweep not repeatable from the repo | `85` and `86` carry the sweep (sections 2, 8, 9) |

### 16.1 Re-review findings and what changed (Claude Code, 14 Nov 2026, `reviews/stage-4b-spec-rereview`)

| # | Severity | Finding | Change |
|---|---|---|---|
| 1 | HIGH | "Refuse unknown tokens" would stop on Keycloak's own `${username}` placeholders | Only upper-case tokens are checked (6.1) |
| 2 | HIGH | One identity 10001 would break `40` on the Droplet (`/files/checks` belongs to 1001) | `FILES_POD_UID`: 10001 on AWS, 1001 on the Droplet; only the file pod (sections 4, 6.1, 6.4) |
| 3 | MEDIUM | Child scripts undid the frozen kubeconfig | Freeze markers reused by children; only the maker removes the file (6.1) |
| 4 | MEDIUM | `30 --check` left nothing to compare and could not run for AWS during Part B | sha256 lines; placeholder email; render-only skips steps 4–5 (6.1, Part B) |
| 5 | MEDIUM | `85` could not be re-run; the final sweep could not be repeated | Skips finished steps; `--sweep-only` (section 8, Done-when 10) |
| 6 | MEDIUM | Node check fails before, during and after the node exists | Part A scripts do not use `target.sh`; a separate "no node yet" message (6.1) |
| 7 | MEDIUM | The access log would record paths, query strings and visitors' addresses | All fields dropped except address, status, time and the marker; visitor-address exception asked of Aziz (section 4) |
| 8 | LOW | Sign-in time cannot come from file times | `83-aws-login.sh` records it (sections 3, 7, 12) |
| 9 | LOW | Terraform reading the `aws login` session not proven | UNVERIFIED 9, proven by `81`'s plan and `82`'s init; fallback without keys |
| 10 | LOW | Replaced node could leave its disk | `delete_on_termination`, checked after replacement (sections 4, 9) |
| 11 | LOW | EBS CSI controller and hop limit 1 | Region in the add-on configuration; UNVERIFIED 10 (sections 4, 12, 14) |
| 12 | LOW | Check lock and fixed ports across targets | Lock stays shared; wording narrowed (section 4, Part B) |
| 13 | LOW | Place of `35` not confirmed | Builder confirms the whole order (section 10) |
| 14 | LOW | `86` numbering, INFO line and "read-only" contradictions | Fixed (sections 2, 9) |
| 15 | LOW | Contracts "not changed" vs Part B's two sentences | Exception named (sections 11, 15) |
| 16 | LOW | Aziz's yes must be in the spec before the merge | Base commit wording (header, section 0) |
| 17 | LOW | IAM sweep relied on unrequired names | All IAM named `ooh-aws-*` and tagged (section 4) |

### 16.2 Round 3 findings and what changed (Claude Code, 14 Nov 2026, `reviews/stage-4b-spec-rereview-2`)

| # | Severity | Finding | Change |
|---|---|---|---|
| 1 | HIGH | A re-run of `85` skipped the destroy that had failed (the cluster goes before the VPC) | Each step decides from Terraform state (section 8) |
| 2 | MEDIUM | Part A's done-when needed an AWS plan while Codex works | Offline checks only; real plans at the run phase (section 7) |
| 3 | MEDIUM | Nobody made `~/.config/ooh/aws/do.env` | `81` makes it (6.2, Part A) |
| 4 | MEDIUM | The left-over-disk check would flag healthy data volumes | Checks only the old root disk, after pods are back (section 9) |
| 5 | LOW | sha256 lines carried the temporary folder | Relative paths, sorted (6.1) |
| 6 | LOW | Sign-ins outside `83`; long scripts not covered by the 11-hour rule | `83` everywhere; `85` and `86 --replace-node` covered (sections 3, 7, 12, 14) |
| 7 | LOW | EBS tag did not name the cluster; launch templates not swept | the cluster-tag argument; launch templates added (sections 4, 8, 12) |
| 8 | LOW | One yes but two Terraform prompts in destroy | Saved destroy plans, one question (section 8) |
| 9 | LOW | Two lists of `aws.env` contents disagreed | One list; roots share values through remote state (6.2, 6.3) |
| 10 | LOW | `terraform validate` cannot init the S3 backend during the Part | `init -backend=false` (sections 2, 7) |
| 11 | LOW | The "control plane only" plan could pull in the NAT gateway | Plan (1) refuses NAT gateway and address, lists every resource with its cost (section 7) |

### 16.3 Round 4 findings and what changed (Claude Code, 14 Nov 2026, `reviews/stage-4b-spec-rereview-3`)

| # | Severity | Finding | Change |
|---|---|---|---|
| 1 | MEDIUM | `/readyz` is readable by every signed-in identity, so it proves no admin rights | `can-i '*' '*'`, `get namespaces`, access entries recorded (sections 7, 12, 14) |
| 2 | MEDIUM | A saved plan never gets Terraform's own "yes" | The script asks in its own words, then applies the saved plan (section 7) |
| 3 | LOW | Header said one exception; there are two | Fixed (header) |
| 4 | LOW | "Belongs to the running copy" undefined | Five rules (section 9 item 11) |
| 5 | LOW | Destroy wait could wait on the node's own disk | Wait condition narrowed; `--ignore-not-found` (section 8) |
| 6 | LOW | Plan files not private | Mode 700/600, deleted after use (sections 7, 8) |

### 16.4 Round 5 findings and what changed (Claude Code, 14 Nov 2026, `reviews/stage-4b-spec-rereview-4`)

| # | Severity | Finding | Change |
|---|---|---|---|
| 1 | MEDIUM | The destroy wait could end while data disks were still attached, leaving them billing | Waits for the pods to go first; wait on the two tag conditions only (section 8) |
| 2 | MEDIUM | The node's own instance failed the "belongs" rules | Rule (f); IAM checked by rule (a) only (section 9) |
| 3 | LOW | Order inside `82`; access-entry output could put the account ID in a file | Kubeconfig and endpoint written right after plan (1); output to the terminal only, account masked (section 7) |
| 4 | LOW | Wrong cross-reference; plan (3) cost line missed the load balancer; one yes or three | Section 4 reference; controller-made items priced; spec author's default: Aziz's one yes covers `82`'s three prompts, total shown first (Aziz may change this) |
| 5 | LOW | Plan files not private in practice | `umask 077`, `install -d -m 700` (section 7) |

### 16.5 Round 6 findings and what changed (Claude Code, 14 Nov 2026, `reviews/stage-4b-spec-rereview-5`)

| # | Severity | Finding | Change |
|---|---|---|---|
| 1 | MEDIUM | Terminated instances and deleted NAT gateways stay listed for about an hour, so clean sweeps would FAIL | `terminated`/`deleted` count as gone; transitional states waited on (sections 8, 9) |
| 2 | LOW | The total cannot be read from plans before plan (1); one yes would cover unseen plans | Fixed price table for the total; later plans checked against an expected list of paid types, stop for a new yes (section 7) |
| 3 | LOW | The "one yes" default is Aziz's decision | Moved into the header and section 0 as a third item he answers before the merge |
| 4 | LOW | Left-over check pods could block the destroy wait | Owner-less pods deleted first; finished pods not counted (section 8) |

### 16.6 Round 7 findings and what changed (Claude Code, 14 Nov 2026, `reviews/stage-4b-spec-rereview-6`)

| # | Severity | Finding | Change |
|---|---|---|---|
| 1 | MEDIUM | The sweep never looked for the EKS cluster, the node group's Auto Scaling group, subnets, route tables, internet gateway or instance profiles | Added (section 8 step 6; section 9 item 11 inherits it) |
| 2 | LOW | Counting paid types could not tell "unchanged" from "rebuilt" | Counts `create` actions; any paid `delete` stops; exact expected creates per plan (section 7) |
| 3 | LOW | Item 9 did not prove locking, and was not read-only | Reworded; the lock object named as an exception to read-only (section 9) |

### 16.7 Round 8 finding and what changed (Claude Code, 14 Nov 2026, `reviews/stage-4b-spec-rereview-7`)

| # | Severity | Finding | Change |
|---|---|---|---|
| 1 | LOW | The node group's Auto Scaling group and EKS's own launch template not clearly covered | Rule (f) names the group; `eks:cluster-name` searched for every type; Part A confirms EKS's tags (sections 8, 9) |

### 16.8 Round 9 finding and what changed (Claude Code, 14 Nov 2026, `reviews/stage-4b-spec-rereview-8`)

| # | Severity | Finding | Change |
|---|---|---|---|
| 1 | LOW | Part A (no AWS session) cannot confirm the tags EKS puts on live resources | Part A states expected tags with sources; `82` prints the real tags in the run phase; Claude records them and stops if the sweep tag is missing (section 8) |

### 16.9 Round 10 findings and what changed (Claude Code, 14 Nov 2026, `reviews/stage-4b-spec-rereview-9`)

| # | Severity | Finding | Change |
|---|---|---|---|
| 1 | LOW | The new `82` duty and report line lived only in section 8 | Added to `82`'s entry and Part A's done-when (section 7) |
| 2 | LOW | "Ask the spec author" pointed at Claude itself | Claude stops the run phase and asks Aziz, with the proposed change (section 8) |
| 3 | LOW | Where to read the Auto Scaling group's launch template not said | Both fields named; `82` stops if neither (section 8); `86` item 11 fails if neither (section 9) |

### 16.10 Round 11 findings and what changed (Claude Code, 14 Nov 2026, `reviews/stage-4b-spec-rereview-10`)

| # | Severity | Finding | Change |
|---|---|---|---|
| 1 | LOW | Rule (f) in `86` named `82` and "stops" | `86` item 11 fails and continues (section 9); 16.9 row corrected |
| 2 | LOW | `82`'s entry lacked the two fields, the stop line and exact masking | Added to `82`'s entry, with `<account>` masking and `EKS_LT_ID` saved (sections 6.2, 7) |
| 3 | LOW | The "ask Aziz" path: cost while paused, a "no", branch and review | Cost stated, "no" path, branch and review named; ID saved by `82` so a re-run works (section 8) |

## 17. Changes agreed during the build (override the sections above where they differ)

| # | Change | Who / when |
|---|---|---|
| 1 | EBS CSI add-on keys (`controller.region`, `controller.k8sTagClusterId`, `controller.extraVolumeTags`) taken from the driver's public Helm chart at v1.68.0, plus a run-phase guard in `82` (`describe-addon-configuration` before plan (2); stop if a key is missing). Codex has no AWS access to read the schema | Claude (spec author), answer to Codex A, 14 Nov ~18:22 |
| 2 | Part B may change existing exit-cleanup lines only to chain `ooh_target_cleanup` from `target.sh` (frozen kubeconfig removed by its maker) | Claude (spec author), answer to Codex B, 14 Nov ~18:22 |
| 3 | Traefik chart 42.4.0 names its access-log values `accessLog.*` and `log.*` (not `logs.access.*`); the behaviour is as section 4 asks | Part A report |
| 4 | `82` refuses an EKS add-on build not offered in `ap-southeast-1` before plan (2) (AWS's pages list different build suffixes from the ones recorded in section 4; no pin changed silently) | Part A report |
| 5 | `82`'s paid-resource guard also accepts a re-run with zero paid creates and zero paid deletes; plan (1) has the same guard (one `aws_eks_cluster` create or none); a missing `eks:cluster-name` tag on EKS's launch template prints `FAIL` and `82` carries on to plan (3) while Claude asks Aziz (section 8 step 6) | Part A review + spec author, 14 Nov ~19:00 |
| 6 | `85` signs out (`aws logout`) on every exit of the normal and `--all` modes; waits for the controller's target groups and security groups after the load balancer; a failed tag read counts as "still there"; the sweep reads network-interface tags from `TagSet`; `86` accepts the controller's shared backend security group in the cluster's VPC | Part A reviews, 14 Nov ~19:00–19:15 |
| 7 | `77`, `78` and `79`: check pods print their JSON as one line prefixed `OOH_RESULT `, harness reads only that line (FAIL, never an ERR-trap stop, when missing or duplicated), and librdkafka logging is off in those pods. Cause: librdkafka log lines on stderr mixed into `kubectl logs` and stopped `77` once on the Droplet (older fault, not caused by this stage) | Part B review + spec author, 14 Nov ~19:20 |
| 8 | AWS order: `35` runs again after the Harness deploy (`67`) and before the two apps, as the Stage 2 guide requires on a fresh install | Part B report |
| 9 | Merge: both Parts merged into local branch `stage-4b` (commit `cbfcbc7`), all offline checks re-run clean; `stage-4b` is pushed and merged to `main` only with Aziz's yes after acceptance | Codex A merge report, 14 Nov ~19:57 |
| 10 | Live run: AWS's managed `aws-ebs-csi-driver` add-on (v1.68.0-eksbuild.1) has no `controller.region` and no `controller.k8sTagClusterId` (the public Helm chart has them). `82`'s guard stopped before plan (2) with nothing extra created. Now: region via `controller.env` `AWS_REGION=ap-southeast-1` (the driver skips instance metadata when AWS_REGION is set, cmd/main.go:154-175), cluster tag via `controller.additionalArgs` `--k8s-tag-cluster-id=ooh-aws` (pkg/driver/options.go:128), still producing `kubernetes.io/cluster/ooh-aws=owned`. The real AWS schema is a committed fixture. Reviewed: one LOW (README anchor), fixed | Run phase, 14 Nov 20:05–20:20 |
| 11 | Live run 2: with `controller.env` AWS_REGION set, the managed EBS add-on went CREATE_FAILED ("duplicate entries for key AWS_REGION"): AWS's managed add-on sets AWS_REGION on the controller itself. Now only `controller.additionalArgs` and `controller.extraVolumeTags` are used. The failed add-on is tainted in Terraform state; the resumed plan (2) must show only `aws_eks_addon.ebs` replaced and nothing paid (Claude checks this on screen before typing yes). README wording for this resume case (review 4 findings 2–3) is fixed after the run | Run phase, 14 Nov 20:33–20:45 |
| 12 | Live run 3: on the resumed run, plan (2) correctly showed only the tainted `aws_eks_addon.ebs` replaced, but `82`'s paid guard crashed before the prompt ("python3: Argument list too long"): the whole plan JSON went through an environment variable, and real plans pass Linux's ~128 KB per-string limit. Nothing was applied. New rule for `install/80`–`86`: JSON from aws, terraform, kubectl or jq reaches Python and jq only on stdin, never through an environment variable or a command-line argument. A 2 MiB plan fixture reproduces the old crash and passes now. `86`'s fixed image list moved inside the jq program (same rule, accepted). Known and accepted: if the producer itself fails (for example an expired sign-in), the run still stops, but a Python traceback appears under the AWS or Terraform error (review 6 finding 1). Reviewed in review 6 | Run phase, 14 Nov 21:00–21:12 |
