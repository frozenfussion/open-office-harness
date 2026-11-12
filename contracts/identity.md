# Identity contract v1

Issuer: https://auth.faysalaziz.com/realms/ooh. Realm: `ooh`.
Realm roles: `ooh-admin`, `ooh-user`. Self-registration is on; a newcomer waits for approval. Brute-force protection is on. Access tokens last five minutes.

| Client | Type | Use |
|---|---|---|
| ooh-workspace | Public, authorization code with PKCE S256 | Workspace; redirect URIs on https://harness.faysalaziz.com only |
| ooh-admin-console | Public, authorization code with PKCE S256; device sign-in disabled | Admin Console; redirect URIs on https://admin.faysalaziz.com only |
| ooh-harness-api | Confidential, service accounts | Harness service-to-service client credentials |
| ooh-control-centre | Confidential, service accounts | Control Centre service-to-service client credentials |
| ooh-model-gateway | Confidential, service accounts | Gateway service-to-service client credentials |
| ooh-slides-worker | Confidential, service accounts | Non-streamed Gateway calls for Slides jobs; audience ooh-model-gateway |
| ooh-safety-watcher | Confidential, service accounts | Gateway classification; audience ooh-model-gateway |
| ooh-stage-check | Confidential, service accounts; disabled between checks | Temporary realm ooh-admin; audiences ooh-control-centre and ooh-harness-api |

UIs send bearer access tokens. Each receiving service validates the signature
using the realm public keys, issuer, expiry and intended audience. `sub` is
`user_id`; `realm_access.roles` supplies realm roles. Service-to-service calls
use client credentials, never user passwords. User tokens may pass only their own
sub as user_id. Authorized service accounts may pass user_id on behalf of a user
(for example, the Harness checking that user's rights). The receiving service
must verify that the calling service is authorized for this delegated operation;
a supplied user_id never grants access by itself. Health is the only
unauthenticated HTTP route.

Each API checks that aud (a string or array) contains its own client ID:

| API | Required audience |
|---|---|
| Harness API | ooh-harness-api |
| Control Centre | ooh-control-centre |
| Model Gateway | ooh-model-gateway |
| Audit writer | ooh-audit-writer (custom audience) |
| Cost meter | ooh-cost-meter (custom audience) |

Clients obtain tokens for the API they call. A token for another audience must
be refused even if its issuer and signature are valid.

| Service account | HTTP rights |
|---|---|
| ooh-harness-api | Control Centre POST /api/access/observe with the exact verified user sub, bounded profile fields, is_service_account and is_admin from verified access-token realm roles; rights checks, rights lists and allowed skill manifests; Gateway purpose calls and classification, on behalf of the user |
| ooh-control-centre | Gateway pinned connection tests only: /v1/call with the fixed OK message and no tools; /v1/classify with the fixed connection-test text/question; admin-test- user ID. Audiences ooh-model-gateway, plus custom ooh-audit-writer and ooh-cost-meter for reading trail/counts/costs |
| ooh-model-gateway | Control Centre GET /api/models and GET /api/models/{id}/key on internal port 8081 only; provider keys encrypted in the Control Centre; no rights grants or skill jobs |

The Harness and workers call the Gateway with tokens for ooh-model-gateway.
Worker service accounts are specified when workers are built. Registry replies
are restricted to the Gateway service account; user tokens cannot read endpoint
configuration or secret references.

Rights are deterministic Control Centre decisions. Roles alone do not let the
Harness infer a skill or tier grant. No answer means not allowed. Workers receive
already authorized jobs, rather than checking rights themselves.

## Kafka credentials and rights

SCRAM-SHA-512, internal listener 9092, simple authorization; one credential per
service. Names below identify principals. All unlisted topic access is denied.
Each consumer uses its own consumer group, with read access only to that group.
All principals below are created by Stage 3. Topic writes grant Write and Describe; topic reads grant Read and Describe; groups grant Read. Resource names are literal.

| Principal | Write | Read | Group |
|---|---|---|---|
| ooh-smoke | ooh.smoke | ooh.smoke | ooh-smoke |
| harness-api | skill.requests.slides, approvals.requested, audit.events, chat.messages, dlq.skill.results, dlq.approvals.decided | skill.results, approvals.decided | harness-api |
| slides-worker | skill.results, audit.events, dlq.skill.requests.slides | skill.requests.slides | slides-worker |
| control-centre | approvals.decided, audit.events, dlq.approvals.requested | approvals.requested, dlq.skill.requests.slides, dlq.skill.results, dlq.approvals.requested, dlq.approvals.decided, dlq.audit.events, dlq.chat.messages | control-centre |
| ooh-stage-check | approvals.requested, skill.requests.slides, chat.messages | approvals.decided, audit.events, skill.results | ooh-stage-check |
| audit-writer | audit.events, dlq.audit.events | audit.events | audit-writer |
| safety-watcher | approvals.requested, audit.events, dlq.skill.results, dlq.chat.messages | chat.messages, skill.results | safety-watcher |
| cost-meter | audit.events, dlq.audit.events | audit.events | cost-meter |
| model-gateway | audit.events | none | none |

The ooh-model-gateway service account uses the model-gateway Kafka principal:
it may write audit.events and has no Kafka read rights.

Every service may emit audit events. Each consumer may write the corresponding
DLQ after its fixed retry limit. The Admin Console accesses DLQ view/replay
through the Control Centre; browser clients never get Kafka credentials. Replay
permissions and routes are deferred to their stage; no broad producer rights
are granted here. Safety watcher may raise an approval request, never a skill
job. The `ooh-smoke` principal must be refused writes to `skill.results`.

The `control-centre` consumer group is exactly `control-centre`. The
`ooh-stage-check` principal uses only group `ooh-stage-check`; it is reserved for
installation checks and cannot borrow a production service's identity. Its
short-lived check pods are removed after each check. DLQ viewing is available through the Control Centre; replay remains deferred.

The shared helper `install/lib/stage-check.sh` is used by checks 62, 73 and 77.
It holds `~/.config/ooh/stage-check.lock` with the check's PID, refuses a concurrent
check, and takes over a stale lock only after its PID is gone. Enabling and
disabling the client each regenerate its secret. Exit cleanup disables the
client; normal completion reads back that it is disabled. Secrets and fresh
tokens live only in shell variables and reach HTTP tools through standard input.
Tokens use the normal client-credentials grant; the audience argument is a local
guard, never an audience parameter sent to Keycloak. Platform check 40 refuses
an enabled client with no running check. Admin-console device sign-in is disabled.

Workspace rights require an approved Control Centre access row. Pending, rejected, closed or unknown people receive no grants, including Everyone. Realm administrators are approved automatically when observed; adding a user grant also approves access. Registration and admission are separate: passwords remain in Keycloak, never in the Control Centre. Device sign-in is disabled; installation checks use the temporary check client.

Only the `ooh-harness-api` service account may POST Control Centre
`/api/tier-requests` on behalf of the signed-in subject. A valid token alone does
not grant admission: the person's access must be approved and the tier must be
requestable. The Control Centre enforces the per-person 20-pending cap and
seven-day retry interval after rejection. Realm administrators alone may list,
count, approve or reject `/api/admin/tier-requests`; an administrator's token
cannot submit the Harness-only route. Both decisions fail closed when the
person's access is no longer approved. Model-request audit detail excludes the
reason and profile fields; request text is never logged.

Only ooh-harness-api submits skill requests on behalf of an approved person.
The same pending caps and rejection cooldown as model requests apply. The Slides
worker may call /v1/call only non-streamed and without pinning a model entry;
the safety watcher may call /v1/classify. Both receive ooh-model-gateway audience
mappers. No worker receives registry keys. The check client's admin role is used
only while its shared lock is held.
