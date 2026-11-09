# open-office-harness — Modules and Contracts (v0.1, planning draft)

Date: 2026-11-07 · Status: draft for Aziz's review · Goes with `architecture-v0.2.png`
Planning only — no code. Becomes `docs/ARCHITECTURE.md` + `contracts/` in the product repo when development starts.

---

## Part 1 — Modules (what each part owns)

| # | Module | Built as | Stack | Owns | Never does |
|---|---|---|---|---|---|
| M1 | Workspace UI | App | Angular | Chat screen, uploads, skill outputs, approvals inbox | Talk to Kafka, Control Centre DB or models directly |
| M2 | Admin Console UI | App | Angular | Users' rights, tiers, models, skills, approvals, audit screens | Talk to the Harness |
| M3 | Control Centre | **Modular monolith** | C# / .NET + PostgreSQL | Rights (tiers, skills), model registry, skill registry, approval rules, audit query | Call AI models |
| M4 | Harness API | Service | Python | Conversations, agent loop, context assembly, classifier routing, offering allowed skills as tools, streaming | Decide rights itself; store secrets |
| M5 | Model Gateway | Service | Python | One door to all AI: chat (tier 1/2), classification, image; keys, rate limits, cost, failover | Know who the user is beyond `user_id` for cost |
| M6 | Skill workers (Slides, Animated deck, Report, + students') | **Microservices** | Python (one may be C#) | One skill each: consume request → produce file → publish result | Check rights (already checked before the job exists) |
| M7 | Read-only consumers (Audit writer, Safety watcher, Cost meter) | Microservices | Python | Read events, write their own store, raise flags | Publish jobs or change anything upstream |
| M8 | Platform | Infra | Keycloak, Kafka, PostgreSQL, object storage, Kubernetes manifests | Sign-in, topics + ACLs, databases, buckets, deployment | Business logic |
| — | Instruction skills | Folders | `SKILL.md` (Agent Skills format) | Know-how loaded into the Harness context | Run code |

**Database ownership:** each service owns its own database/schema. Nobody reads another service's tables — they ask through the contract.

---

## Part 2 — Contracts (how parts talk)

### C1 Sign-in and identity (Keycloak, OIDC)
- Users sign in through Keycloak; UIs send the access token on every call.
- Every service validates the token itself (Keycloak public keys).
- Service-to-service calls use their own Keycloak service accounts (client credentials), never a user's password.
- Kafka: each service has its own credentials; ACLs decide who may write/read each topic (e.g. only the Harness may write `skill.requests.*`).

### C2 Rights check — Harness → Control Centre (sync, fail closed)
`POST /api/rights/check`
```json
{ "user_id": "u-123", "action": "skill.use", "target": "slides" }
→ { "allowed": true, "reason": "Role 'analyst' has skill.slides", "decided_by": "role:analyst" }
```
`GET /api/rights/me?user_id=u-123`
```json
→ { "chat_tiers": [1], "skills": ["slides", "report"], "image": false }
```
- Actions: `chat.tier` (target "1"/"2"), `skill.use` (target skill name), `image.generate`.
- Control Centre down or no answer → **not allowed**. The Harness may cache `/me` for a short time (setting, starting 30 s).

### C3 Skill manifest — registered in Control Centre
```json
{
  "name": "slides",
  "title": "Presentation (.pptx)",
  "kind": "service",                       // "service" (worker) or "instruction" (SKILL.md)
  "description": "Creates a PowerPoint deck from a topic and notes",
  "input_schema": "contracts/skills/slides.input.json",
  "output_schema": "contracts/skills/slides.output.json",
  "right": "skill.slides",
  "needs_approval": false,
  "topic": "skill.requests.slides",
  "version": "1.0.0"
}
```
`GET /api/skills?user_id=u-123` → only the manifests this user may use. The Harness turns these into tools for the model. Unlisted = invisible.

### C4 Model Gateway — Harness/workers → Gateway (sync)
`POST /v1/call` (streams when `stream: true`)
```json
{ "purpose": "chat", "tier": 2, "user_id": "u-123", "messages": [...], "attachments": [...], "stream": true }
```
`POST /v1/classify`
```json
{ "text": "...", "questions": { "needs_tier2": "Does this need deep reasoning or long analysis?",
                               "wants_slides": "Is the user asking for a presentation?" } }
→ { "needs_tier2": 0.81, "wants_slides": 0.93 }
```
- Which provider serves a purpose/tier comes from the Control Centre model registry (on-prem or cloud). **No model name or key in code.**
- Classifier answers are suggestions. Thresholds are settings. Every score is logged to `audit.events`.

### C5 Workspace UI ↔ Harness (sync + streaming)
- `POST /api/conversations` → new conversation
- `POST /api/conversations/{id}/messages` → reply streamed (SSE)
- `POST /api/uploads` → file key
- `GET /api/events` (SSE) → job updates: `job.queued`, `job.awaiting_approval`, `job.completed`, `job.failed`
- `GET /api/files/{key}` → short-lived download link

### C6 Kafka — one envelope for every message
```json
{
  "event_id": "uuid",            // unique; consumers ignore repeats (idempotency)
  "type": "skill.requested",
  "version": 1,
  "occurred_at": "2026-11-07T08:30:00Z",
  "correlation_id": "req-uuid",  // ties request → approval → result → audit
  "user_id": "u-123",
  "producer": "harness",
  "payload": { }
}
```
- Message key = `correlation_id` (keeps one request's messages in order).
- Schemas are JSON Schema files in `contracts/`, versioned. A breaking change = new version, old one kept until no one uses it.

### C7 Topics
| Topic | Written by | Read by | Payload (main fields) |
|---|---|---|---|
| `skill.requests.<skill>` | Harness | that skill's worker | manifest `input` |
| `skill.results` | workers | Harness, Audit writer, Safety watcher, Cost meter | `status` (completed/failed), `output` {file_key, mime, summary}, `error` |
| `approvals.requested` | Harness, Safety watcher | Control Centre | `action`, `details`, `risk`, `requested_by` |
| `approvals.decided` | Control Centre | Harness | `approved`, `decided_by`, `note` |
| `audit.events` | every service | Audit writer | `actor`, `action`, `target`, `outcome`, `model`, `tokens`, `scores` |
| `dlq.<topic>` | any consumer after N failed tries | Admin Console (view, replay) | original message + error |

### C8 Flows (how the contracts combine)
**Normal skill:** user asks → Harness classifies → rights check (C2) → publish `skill.requests.slides` → worker builds deck → file to storage → `skill.results` → Harness pushes `job.completed` to the UI.
**Skill with approval:** same, but Harness first publishes `approvals.requested` → admin approves in Admin Console → `approvals.decided` → only then the job is published.
**Tier routing:** classifier says `needs_tier2: 0.81` → rights check `chat.tier 2` → allowed: call tier 2 · not allowed: tier 1 + note "an admin can give you the advanced model".
**Worker down:** jobs wait in the topic; UI shows "queued"; worker returns and catches up. Chat keeps working.

### C9 Object storage
- Keys: `uploads/<user_id>/<uuid>-<name>`, `outputs/<skill>/<correlation_id>/<file>`.
- Downloads only through short-lived signed links from the Harness. Buckets are never public.

---

## Part 3 — What can be built in parallel (after contracts are agreed)
| Window | Builds | Depends on (contract only) |
|---|---|---|
| Codex 1 | M3 Control Centre | C1, C2, C3, C7 approvals |
| Codex 2 | M4 Harness API | C2–C7 |
| Codex 3 | M5 Model Gateway | C4 |
| Codex 4 | M6 Slides worker (first skill) | C3, C6, C7, C9 |
| Codex 5 | M1 + M2 UIs | C5, Control Centre API |
| Opus | Reviews each against its spec + these contracts | — |

## Open points (decide later, not blocking)
- JSON Schema now; a schema registry (with Avro/Protobuf) is a later lesson.
- Exact cache time for rights, retry counts before DLQ, retention days per topic — settings with starting values, decided in the specs.

---

## Part 4 — Deployment (added 16:40, D023–D025)
| Where | What | How it's set up |
|---|---|---|
| **DigitalOcean Droplets** — base sandbox, where the harness really runs | k3s + all app services, Keycloak, Kafka, PostgreSQL (in-cluster), Spaces for files | **By hand, by Aziz** (and participants are expected to be able to do this) |
| **AWS** — production-style target for the EKS demo | EKS (all app pods), MSK (Kafka), RDS PostgreSQL, S3, VPC, IAM | **Terraform only** — no console clicking. Codex writes it, `terraform plan` = Aziz's approval gate, Aziz runs `apply` / `destroy`. State in S3 with native locking. Torn down after demos. |
| Outside both | On-prem models, optional on-prem skill workers | Connect OUT to Kafka |
- Same Helm charts on k3s and EKS — only values files differ.
- AWS credentials: `aws configure` by Aziz on the Terraform machine, least-privilege IAM user. Never in repo, logs or chat.
