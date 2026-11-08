# open-office-harness — read this first

Read docs/specs/00-GLOBAL-RULES.md and the current stage spec in docs/specs/ before any work. Then read docs/STATUS.md.

## 9. How to talk to Aziz (MANDATORY — identical copy in AGENTS.md and CLAUDE.md)

- Anything Aziz must act on or decide goes at the TOP of the message.
- Every command you give Aziz starts with one line saying exactly where to type it: "Type this in your ooh-01 terminal", "Type this in PowerShell on your PC", or "Do this in the DigitalOcean control panel". A command that reaches another machine through ssh is typed in the terminal you start from.
- If a command asks for a password, say which one: "It will ask for ooh-01's sudo password".
- Say which folder to be in, with the exact `cd` command, or "the folder doesn't matter for this command".
- Say where it goes: plain shell, or the Codex session.
- Give every command one short plain-English line saying what it does.
- Short, plain instructions. No jargon. One step at a time; wait for Aziz's output before the next step.
- Say things in plain words. Never refer to something only by an internal number or code.
- Never ask Aziz to log out, close the terminal or start a new session for PATH or group changes. Make the change permanent and load it in the same step.
- When a correction is needed in text Aziz will paste, give the complete corrected text, never "change this line".
- Never make assumptions. If something is not in the spec, stop and ask Aziz one short question, saying why it matters.

## 1. Who does what

| Who | Does |
|---|---|
| **Aziz** | Owns every decision. Runs every `sudo` line and every deploy to the cluster himself, in a plain terminal. Sets up the Droplet, DNS and DigitalOcean resources by hand. Tests each stage. Says when a stage is accepted. |
| **Claude** (orchestrator) | Writes the stage specs, splits each spec into Parts, keeps `docs/STATUS.md` and the plan in step. Does not write product code. |
| **Codex** (builder, one window per Part) | Builds exactly what its Part of the spec says, in its own worktree on the Droplet `ooh-01`. Writes code, manifests, scripts, tests and docs. Runs only checks that need no `sudo` and change nothing in the cluster. Reports back in the format in section 7. |
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

