# open-office-harness — Global rules for every build stage

Applies to every stage spec in this folder. Readers: Codex (builder), Opus (reviewer), Aziz (owner), Claude (spec author).
A stage spec may add rules. It may not remove any rule in this file.
Written 2026-11-08, adapted from the HOORA AI method.

## 1. Who does what

| Who | Does |
|---|---|
| **Aziz** | Owns every decision. Runs every `sudo` line and every deploy to the cluster himself, in a plain terminal. Sets up the Droplet, DNS and DigitalOcean resources by hand. Tests each stage. Says when a stage is accepted. |
| **Claude** (orchestrator) | Writes the stage specs, splits each spec into Parts, keeps `docs/STATUS.md` and the plan in step. Does not write product code. |
| **Codex** (builder, one window per Part) | Builds exactly what its Part of the spec says, in its own worktree on the Droplet `harness`. Writes code, manifests, scripts, tests and docs. Runs only checks that need no `sudo` and change nothing in the cluster. Reports back in the format in section 7. |
| **Opus** (reviewer) | Reviews each finished Part against its spec and this file, with the checklist in section 8, before Aziz tests. |

Codex **never**:
- runs `sudo`, or asks Aziz to type a password into Codex;
- changes the cluster: no `kubectl apply/create/delete/edit/patch/scale`, no `helm install/upgrade/uninstall`. Read-only `kubectl get/describe/logs` is allowed for checks;
- starts a service, server or watcher in the background (`nohup ... &`, `&`, `disown`);
- installs system packages (`apt`), changes the firewall, systemd, k3s or anything under `/etc`;
- pushes to `main` before Aziz has said the stage is accepted;
- changes a file that its Part does not list (another Part owns it);
- puts a password, token, key or real secret value into the repo, a log, a commit message or its report;
- deletes data, migrations, topics or audit rows;
- adds a feature, service, table, topic, dependency or test that the spec did not ask for;
- puts a client's or employer's name, or anyone's personal data, into the repo (this repo is public; the maintainer's name and domain are the only exception).

When Codex needs something only Aziz may do, it writes the exact commands into a script under `install/` and stops with: **"Aziz, please run install/<file> as described in README"**. It does not continue until Aziz says it is done.

## 2. Fixed decisions (do not revisit)

**Product**
- Name `open-office-harness` (short `ooh`). Licence AGPL-3.0. Public repo `github.com/frozenfussion/open-office-harness`.
- Modules and contracts: `docs/ARCHITECTURE.md` and `contracts/`. A module talks to another only through a contract.
- Kafka only where it solves a real problem (slow or bursty work, fan-out, survive a service being down, replay). Chat streaming and rights checks are direct HTTP calls.
- Rights (chat tiers, skills, image) are decided by fixed rules in the Control Centre, never by an AI. If the Control Centre does not answer, the answer is **not allowed** (fail closed). The classifier only *suggests*.
- A tier is a field on each chat model entry (1..N). Creating a new tier creates its right automatically.
- **No AI model name, vendor, address or key in code or config in the repo** (Aziz, 10 Nov 2026: "There's not going to be any hard code"). AI is used by *purpose* (`chat`, `classification`, `image`, and any purpose added later). Which model serves a purpose and tier is a row in the Control Centre's model registry. Tests use a fake model, never a real one.
- Each service owns its own database. Nobody reads another service's tables.
- **Nothing is ever deleted.** Business tables have `deleted_at`; "delete" sets it. The audit trail is append-only, enforced by the database.

**Stack**
- Control Centre: C# on .NET 10 (LTS), ASP.NET Core, EF Core with migrations, PostgreSQL. One deployable, built as a modular monolith.
- Harness API, Model Gateway, skill workers, read-only consumers: Python 3.14.
- Workspace and Admin Console: two separate Angular 22 apps.
- Sign-in: Keycloak (OIDC). Messaging: Apache Kafka (KRaft, no ZooKeeper) run by the Strimzi operator. Database: PostgreSQL 18 run by the CloudNativePG operator. Files: a Kubernetes volume `ooh-files` on the Droplet disk now (agreed 09 Nov 2026: no Spaces, no S3 server); Amazon S3 on AWS in Stage 6.
- Runs on Kubernetes: k3s on the DigitalOcean Droplet now, AWS EKS later, with the same manifests and different values. Container images are built by GitHub Actions (`.github/workflows/`) and go to `ghcr.io/frozenfussion/ooh-<name>`, tagged with the git short hash (agreed 09 Nov 2026: free for a public repo, nothing added to the Droplet).
- Exact versions are fixed and dated in each stage spec.

**Places and names**
- Droplet `harness` (DigitalOcean, 143.198.221.2), password login for user `aziz`. Main clone `~/projects/open-office-harness`; one git worktree per Part under `~/projects/worktrees/`; local settings in `~/.config/ooh/`. Everyone works inside the tmux session `harness`, window `work`, labelled tiles: 0 Codex A (builds), 1 Codex B (builds), 2 Claude Code (reviews), 3 Shell (Aziz, sudo), and from Stage 2 also 4 Codex C (builds), 5 Codex D (builds).
- Public hostnames (A records to `harness`): `harness.faysalaziz.com` = Workspace app, with the Harness API under `/api`; `admin.faysalaziz.com` = Admin Console, with the Control Centre API under `/api`; `auth.faysalaziz.com` = Keycloak. Each app talks only to its own host (no cross-site calls). Model Gateway, Kafka and PostgreSQL have no public name.
- Kubernetes namespaces: `ooh-platform` (Kafka, PostgreSQL, Keycloak) and `ooh-apps` (our services).
- Secrets live only in Kubernetes Secrets, created by scripts Aziz runs. The repo holds `.env.example` files and `*.example.yaml` files with names and no values.
  Two agreed exceptions: AI provider keys are typed by an admin in the Admin Console and stored **encrypted** in the Control Centre's database (the encryption key is a Kubernetes Secret; agreed 10 Nov 2026); and the builders' **test** database settings files under `~/.config/ooh/*-test.env` (mode 600, test databases only).
- Times are stored in UTC. The display time zone is a setting (first value `Asia/Kuala_Lumpur`). All user-facing text is English.

## 3. Repo layout (one repo, fixed)

```
open-office-harness/
  AGENTS.md              read by Codex (same content as CLAUDE.md)
  CLAUDE.md              read by Claude Code
  README.md              starts with the QUICK GUIDE (section 6)
  LICENSE                AGPL-3.0
  docs/
    ARCHITECTURE.md      modules, contracts summary, flows, deployment
    STATUS.md            what is built, what passed, what is open (updated every stage)
    specs/               this file + stage-N-*.md
    images/
  contracts/             the agreements between modules (HTTP, events, skills, storage, identity)
  deploy/
    platform/            cluster pieces: cert-manager, Strimzi + Kafka, CloudNativePG + PostgreSQL, Keycloak, ingress
    apps/                our services' manifests (from Stage 1)
    values/              do.yaml (Droplet), aws.yaml (EKS, Stage 6)
  install/               scripts Aziz runs (setup, secrets, deploy, checks)
  .github/workflows/     image builds (GitHub Actions)                              — from Stage 1
  services/              control-centre (C#), harness-api, model-gateway (Python)   — from Stage 1
  workers/               one folder per skill worker                                — from Stage 3
  consumers/             audit-writer, safety-watcher, cost-meter                   — from Stage 3
  apps/                  workspace, admin-console (Angular)                         — from Stage 4
  infra/terraform/aws/   AWS stack                                                  — Stage 6
```
Each service, worker, consumer and app is its own package with its own lock file and its own Dockerfile. No shared code folder unless a spec creates one.

## 4. Code rules

**All code**
- Pin exact versions (no `^`, `~`, `>=`, `latest`, no untagged image). Commit lock files. Every new dependency is named in the report with one line saying why. No dependency for something the language, PostgreSQL or the browser already does.
- Logs: JSON lines to stdout. Never log request bodies, passwords, tokens, file contents or personal details.
- Every HTTP route validates its input, returns JSON (or a declared stream) and has at least one test. Every route except health needs a valid Keycloak token.
- Every Kafka message uses the envelope in `contracts/events/envelope.schema.json`. Every consumer ignores an `event_id` it has already handled (idempotent), retries a fixed number of times, then sends the message to `dlq.<topic>`. Message key = `correlation_id`.
- No code comments that explain the obvious; a short comment where the reason is not obvious.
- Each source file starts with `// SPDX-License-Identifier: AGPL-3.0-only` (or `#` for Python, YAML and shell).

**C# (.NET 10)**: nullable enabled, warnings as errors, `dotnet format --verify-no-changes` clean, tests with xUnit, `dotnet test` must pass. EF Core migrations only; a migration that has been applied on `harness` is never edited, add a new one.

**Python 3.14**: `uv` for packages and lock file, `ruff check` and `ruff format --check` clean, tests with `pytest`, all must pass. Type hints on every function.

**Angular 22**: standalone components, strict TypeScript, the Angular CLI's own build and test commands, design tokens from the Open Office Harness design system only.

**Kubernetes manifests**: plain YAML, one resource per file where practical, every Deployment with resource requests and limits, readiness and liveness probes, non-root user, read-only root filesystem where the image allows. Every manifest passes `kubeconform -strict` (CRDs: with their schemas, or listed as skipped in the report).

**Shell scripts in `install/`**: `#!/usr/bin/env bash`, `set -euo pipefail`, pass `bash -n` and `shellcheck`. **Never pipe into `head` or `grep -q` under `pipefail`**; capture output into a variable first. Every script is re-runnable without harm and prints `STOP: <plain reason>` and exits non-zero when something is wrong. Every script ends with `DONE` on success.

## 5. Build and deploy flow (every stage)

1. Claude commits the stage spec to `main`. That commit is the stage's **base commit**, written in the spec.
2. Each Part runs in its own Codex window, in its own worktree, on its own branch, made by Codex from the base commit:
   `git -C ~/projects/open-office-harness worktree add ~/projects/worktrees/stage-N-part-x -b stage-N-part-x <base commit>`
3. **Part rule:** a Part changes only the files its spec lists. Part A changes no file Part B lists, and the reverse. If a Part needs to change another Part's file, it stops and asks.
4. When its Part is complete and all checks pass, Codex commits on its branch and writes its report (section 7).
5. Opus reviews each Part. Codex fixes findings on the same branch. Opus re-reviews.
6. Codex merges the Parts into `stage-N` (made from the base commit) and runs all checks again on a clean worktree of `stage-N`.
7. Aziz deploys with the stage's script in `install/` and tests the spec's "Done when" list.
8. When Aziz says the stage is accepted, Codex commits "Stage N: accepted", merges `stage-N` into `main`, pushes, and creates the stage's tag: `git tag -a <tag> -m "Stage N accepted" && git push origin main <tag>`.

Aziz's command-line work is kept to the minimum. Codex runs every git step. Aziz types only what an agent may not do: `sudo` lines, deploys to the cluster, passwords, and steps in the DigitalOcean control panel or on his own PC.

## 6. Documentation rule (instructions come first)

Every `README.md` starts with a **QUICK GUIDE** before anything else: short numbered steps, exact copy-paste commands, the terminal to type each in, and the good result of each, written so simply that a six-year-old can follow. It covers every everyday job for what exists so far: set up, deploy, check, start, stop, restart, status, logs, run tests, what each `STOP:` message means, and what to do after a reboot. Details come after the Quick Guide. Codex updates the README in every stage.

Every Part also writes, in its report, what an instructor needs on the day: the commands Aziz ran, what he saw, what failed and how it was fixed, and how long it took. Claude turns this into the instructor runbook (kept in the private course repo, not here).

## 7. Codex report format (end of every Part)

```
STAGE N PART X REPORT
1. Built: <files/folders added or changed, one line each>
2. Dependencies added: <name, exact version, why> (or "none")
3. Checks run and results: <each check, passed/failed, counts>
4. Things I could not do (needed sudo / the cluster / network / a decision): <list>
5. Deviations from the spec: <none, or each one with the reason>
6. Open questions for Aziz: <one per line, plain words, why it matters>
7. For the runbook: <what Aziz ran, what he should see, what failed and the fix, time taken>
```

## 8. Opus review checklist (every Part)

1. Does every item in the Part's "Done when" exist and work? Run the checks yourself where possible.
2. Did the Part change any file it does not list? (Must be none.)
3. Any `sudo`, `apt`, background process, `/etc` change or cluster change made by Codex? (Must be none.)
4. Any model name, vendor, address, key, token or secret in code, config, manifests or docs? (Must be none.)
5. Any client or employer name, or personal data (beyond the maintainer's name and domain)? (Must be none.)
6. Any hard delete, any update/delete path to audit rows, any business table without `deleted_at`? (Must be none.)
7. Any dependency not justified in the report? Any version not pinned exactly? Any image without a fixed tag?
8. Any route without input validation, without a test, or (except health) without a token check?
9. Any Kafka consumer that is not idempotent, has no retry limit or no dead-letter topic? Any message not in the envelope?
10. Any script that pipes into `head`/`grep -q` under `pipefail`, is not re-runnable, or lacks `STOP:`/`DONE`?
11. Any manifest without requests/limits, probes or non-root user, or failing `kubeconform`?
12. README Quick Guide: present, first, complete for this stage, plain words?
13. `docs/STATUS.md` updated?
14. Anything built that the spec did not ask for?

Report findings as a numbered list: file, line, what is wrong, what the spec says. No praise, no summary of what is fine.

## 9. How to talk to Aziz (MANDATORY — identical copy in AGENTS.md and CLAUDE.md)

- Anything Aziz must act on or decide goes at the TOP of the message.
- Every command you give Aziz starts with one line saying exactly where to type it: "Type this in your harness terminal", "Type this in PowerShell on your PC", or "Do this in the DigitalOcean control panel". A command that reaches another machine through ssh is typed in the terminal you start from.
- If a command asks for a password, say which one: "It will ask for harness's sudo password".
- Say which folder to be in, with the exact `cd` command, or "the folder doesn't matter for this command".
- Say where it goes: plain shell, or the Codex session.
- Give every command one short plain-English line saying what it does.
- Short, plain instructions. No jargon. One step at a time; wait for Aziz's output before the next step.
- Say things in plain words. Never refer to something only by an internal number or code.
- Never ask Aziz to log out, close the terminal or start a new session for PATH or group changes. Make the change permanent and load it in the same step.
- When a correction is needed in text Aziz will paste, give the complete corrected text, never "change this line".
- Never make assumptions. If something is not in the spec, stop and ask Aziz one short question, saying why it matters.
