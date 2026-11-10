# open-office-harness architecture

![Modules and synchronous/asynchronous flows](images/architecture-v0.2.png)

Stage 2 implements direct streamed chat: the Workspace, Harness API and Model
Gateway, plus Models & tiers in the Admin Console and the Control Centre registry.
The skill workers and read-only consumers below arrive in Stage 3.
The fixed stage specifications and global rules take precedence over the planning
image: deployment uses plain Kubernetes manifests, and each service has its own
database rather than shared tables.

| Module | Owns | Never does |
|---|---|---|
| Workspace (Angular 22) | Sign-in, allowed tiers, conversations and streamed chat; uploads and approvals later | Contact Kafka, models or the Control Centre database |
| Admin Console (Angular 22) | Models & tiers, encrypted key entry and tier grants; other screens later | Contact the Harness directly |
| Control Centre (.NET 10 modular monolith) | Deterministic rights, model and skill registries, approval rules, its own append-only change log and audit query | Call AI models |
| Harness API (Python 3.14) | Conversations, last 20 completed messages, rights checks, allowed tools and streaming; classifier later | Decide rights or store secrets |
| Model Gateway (Python 3.14) | Purpose/tier routing, credentials, rate limits, cost and failover | Know who the user is beyond user_id for cost |
| Skill workers (Python 3.14) | One skill each; requests, files and results | Check rights after a job is published |
| Audit writer | Append-only audit store | Change upstream business state or publish jobs |
| Safety watcher | Read events and raise approval flags | Publish skill jobs or grant rights |
| Cost meter | Read usage events and write its own store | Change upstream business state |
| Platform | Keycloak identity, Kafka topics and ACLs, PostgreSQL, private storage, Kubernetes | Business logic |
| Instruction skills | Know-how loaded as context from SKILL.md | Run worker code |

## Agreements between modules

- [Identity](../contracts/identity.md): users authenticate through Keycloak;
  every service validates its own token. Service calls use service accounts.
- [Control Centre HTTP](../contracts/http/control-centre.openapi.yaml): rights,
  allowed manifests and purpose/tier assignments. No reply to a rights check means
  not allowed. The optional rights-list cache starts at 30 seconds; it must not
  turn an unavailable rights decision into permission for a new job.
- [Gateway HTTP](../contracts/http/model-gateway.openapi.yaml): AI calls by
  purpose and tier, plus classifier scores. Scores suggest; fixed policy decides.
  A tier is a positive integer field on a chat registry entry; creating one also
  creates its right. Registry assignments and credentials are runtime data.
- [Harness HTTP](../contracts/http/harness-api.openapi.yaml): conversations,
  message streaming, uploads, job updates and signed downloads.
- [Events](../contracts/events/envelope.schema.json): all business-event records
  share an envelope; the Kafka key is correlation_id. Consumers ignore duplicate event_id
  values, retry a fixed configured number of times, then publish to dlq.<topic>.
  Retry counts are specified when consumers are built. The ooh.smoke
  platform-check topic is free-form with no schema or envelope.
  Topic retention and
  partitions are fixed in [topics.yaml](../contracts/events/topics.yaml).
- [Skills](../contracts/skills/manifest.schema.json): a manifest declares the
  permission, approval need and input/output shapes. Only allowed skills appear
  as model tools. Slides produces a PowerPoint file.
- [Storage](../contracts/storage.md): files use private object keys and
  short-lived signed download links.

## Flows

**Normal skill (Stage 3):** Workspace sends a request to the Harness. The Harness asks the
classifier for suggestions, checks rights with the Control Centre, publishes to
skill.requests.slides, and shows queued. The worker writes an output to storage
and publishes skill.result. The Harness sends job.completed to the Workspace.

**Approval (Stage 3):** before publishing a job, the Harness publishes approval.requested.
The Control Centre handles the admin's decision through the Admin Console and
publishes approval.decided. Only an approved request with valid rights proceeds;
a rejected request never becomes a skill job. The UI shows awaiting approval.

**Chat (Stage 2):** both apps sign in through Keycloak with code + PKCE S256
and session storage. Each reads its issuer, client ID and same-host API path from
`/config.json`. Workspace shows only allowed chat tiers and the user's ID with a
copy button for grants. It sends a question to its own Harness API. The Harness
checks the conversation owner and asks the Control Centre for `chat.tier` with
the selected tier. Missing policy fails closed. A refused tier is a 403 with a
plain message; it is not sent to a model. The browser renders all chat text as
plain text with line breaks and reads the POST answer using fetch and SSE.

The Harness sends the last 20 completed, nonempty conversation messages,
starting with a user message, then the new question, with no system message.
Only allowed skills are offered as tools. A tool request produces a fixed
sentence saying skills arrive in the next stage; it runs no job. Conversations
belong to the Harness database, and messages cannot be updated or deleted.

The Gateway resolves purpose and tier from the Control Centre registry on
internal port 8081. It tries main entries before backup entries, then priority
and creation time. A failure before output may try the next entry; a failure
after output ends the stream. Per-entry, per-user rate limits use the last 60
seconds of completed/failed usage. Per-entry budgets use the UTC day's cost.
When every entry is over budget, the Harness can fall back to the lowest allowed
tier and includes a note. Usage and calculated cost live in the Gateway's own
append-only database; no Kafka messages are produced for chat in Stage 2.

**Tier routing (Stage 3):** a classifier score may suggest a higher tier. The
Harness will check `chat.tier` before using it. The planned classifier fallback
to a separately allowed lower tier with a note belongs to that routing flow;
it does not override Stage 2's refusal of an explicitly requested forbidden tier.
Unavailable policy always fails closed.

**Worker down:** Kafka retains queued jobs. The worker catches up when it returns,
with duplicate-event handling. Chat remains a direct HTTP stream and continues
without waiting for workers or read-only consumers.

## Data and deployment

Each service owns its own PostgreSQL database. The Harness owns conversations;
the Control Centre owns policy, registries and its own append-only change log.
It saves each change, its audit row and outgoing events in one database
transaction; an outbox publisher sends the events to Kafka. The Audit writer
(Stage 3) keeps the full trail across services by consuming audit.events.
Other modules use contracts and never query those tables directly. Business
records use deleted_at; audit records are append-only with database enforcement.
Stage 0 creates Keycloak's database; Stage 1 adds the Control Centre database,
and Stage 2 adds separate Harness and Gateway databases. All stored times are UTC; the initial
display setting is Asia/Kuala_Lumpur. User-facing text is English.

The Stage 2 services and both apps run in ooh-apps. The following storage
paragraph is retained pending the Stage 3 storage contract rewrite.

The rehearsal runs on the DigitalOcean Droplet harness: single-server k3s,
Traefik ingress, cert-manager, Strimzi Kafka, CloudNativePG PostgreSQL and
Keycloak in ooh-platform. Services later run in ooh-apps. Spaces stores private
files. Workspace and its /api share harness.faysalaziz.com; Admin Console and
its /api share admin.faysalaziz.com; Keycloak uses auth.faysalaziz.com. Gateway,
Kafka and PostgreSQL have no public hostname.

Stage 6 moves to AWS EKS with the same manifests and different values, and S3
storage. AWS infrastructure uses Terraform; Aziz performs deployments. Secrets
are Kubernetes Secrets created by setup scripts, never repository values.
Admins type provider keys once in the Admin Console. The Control Centre stores
them encrypted with AES-256-GCM using a Kubernetes encryption-key Secret and the
entry ID as associated data. Admin responses expose only `has_key`. Only the
Gateway service account may retrieve a decrypted key, on internal port 8081;
registry and key routes return 404 on public port 8080. Keys follow their endpoint
and connection type: changing either clears the saved key unless replaced.
The Gateway caches registry data for 30 seconds and keys for 60 seconds.
Its three adapters implement the connection formats chosen per registry entry;
provider addresses, models and prices are registry data, never compiled settings.
Kafka is used for slow work, fan-out, outage survival and replay; chat and policy
checks use direct HTTP. Stage 2 deploy/check scripts run in Claude's shell tile while Aziz watches;
Aziz retains sudo, browser sign-ins, package visibility switches and acceptance.
