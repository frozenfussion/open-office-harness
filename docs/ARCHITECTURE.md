# open-office-harness architecture

![Modules and synchronous/asynchronous flows](images/architecture-v0.2.png)

Stage 0 defines boundaries and contracts. Product services arrive in later stages.
The fixed stage specifications and global rules take precedence over the planning
image: deployment uses plain Kubernetes manifests, and each service has its own
database rather than shared tables.

| Module | Owns | Never does |
|---|---|---|
| Workspace (Angular 22) | Chat, uploads, outputs, approval inbox | Contact Kafka, models or the Control Centre database |
| Admin Console (Angular 22) | Rights, tiers, registry, skills, approvals and audit screens | Contact the Harness directly |
| Control Centre (.NET 10 modular monolith) | Deterministic rights, model and skill registries, approval rules, its own append-only change log and audit query | Call AI models |
| Harness API (Python 3.14) | Conversations, agent loop, context, classifier routing, allowed tools, streaming | Decide rights or store secrets |
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

**Normal skill:** Workspace sends a request to the Harness. The Harness asks the
classifier for suggestions, checks rights with the Control Centre, publishes to
skill.requests.slides, and shows queued. The worker writes an output to storage
and publishes skill.result. The Harness sends job.completed to the Workspace.

**Approval:** before publishing a job, the Harness publishes approval.requested.
The Control Centre handles the admin's decision through the Admin Console and
publishes approval.decided. Only an approved request with valid rights proceeds;
a rejected request never becomes a skill job. The UI shows awaiting approval.

**Tier routing:** a classifier score may suggest a higher tier. The Harness
checks chat.tier for that tier before calling the Gateway. A denial falls back
to separately allowed tier 1 plus a note: "an admin can give you the advanced
model". Unavailable policy fails closed.
The Gateway reads the Control Centre registry to resolve purpose and tier.

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
Stage 0 creates only Keycloak's database. All stored times are UTC; the initial
display setting is Asia/Kuala_Lumpur. User-facing text is English.

The rehearsal runs on the DigitalOcean Droplet harness: single-server k3s,
Traefik ingress, cert-manager, Strimzi Kafka, CloudNativePG PostgreSQL and
Keycloak in ooh-platform. Services later run in ooh-apps. Spaces stores private
files. Workspace and its /api share harness.faysalaziz.com; Admin Console and
its /api share admin.faysalaziz.com; Keycloak uses auth.faysalaziz.com. Gateway,
Kafka and PostgreSQL have no public hostname.

Stage 6 moves to AWS EKS with the same manifests and different values, and S3
storage. AWS infrastructure uses Terraform; Aziz performs deployments. Secrets
are Kubernetes Secrets created by Aziz's scripts, never repository values.
Kafka is used for slow work, fan-out, outage survival and replay; chat and policy
checks use direct HTTP. Stage 0 builds no product implementation.
