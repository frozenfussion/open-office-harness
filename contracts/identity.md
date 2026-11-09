# Identity contract v1

Issuer: https://auth.faysalaziz.com/realms/ooh. Realm: `ooh`.
Realm roles: `ooh-admin`, `ooh-user`. Self-registration is off; later sign-ups
use approvals. Brute-force protection is on. Access tokens last five minutes.

| Client | Type | Use |
|---|---|---|
| ooh-workspace | Public, authorization code with PKCE S256 | Workspace; redirect URIs on https://harness.faysalaziz.com only |
| ooh-admin-console | Public, authorization code with PKCE S256; device sign-in during Stage 1 | Admin Console; redirect URIs on https://admin.faysalaziz.com only |
| ooh-harness-api | Confidential, service accounts | Harness service-to-service client credentials |
| ooh-control-centre | Confidential, service accounts | Control Centre service-to-service client credentials |
| ooh-model-gateway | Confidential, service accounts | Gateway service-to-service client credentials |

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

Clients obtain tokens for the API they call. A token for another audience must
be refused even if its issuer and signature are valid.

| Service account | HTTP rights |
|---|---|
| ooh-harness-api | Control Centre rights checks, rights lists and allowed skill manifests; Gateway purpose calls and classification, on behalf of the user |
| ooh-control-centre | Its Control Centre operations subject to fixed policy; no AI calls |
| ooh-model-gateway | Control Centre GET /api/models for purpose/tier registry lookup; no rights grants or skill jobs |

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
Future principals are created only in their implementation stages.

| Principal | Write topics | Read topics | Created |
|---|---|---|---|
| ooh-smoke | ooh.smoke | ooh.smoke | Stage 0 |
| harness-api | skill.requests.slides, approvals.requested, audit.events, dlq.skill.results, dlq.approvals.decided | skill.results, approvals.decided | Later |
| slides-worker | skill.results, audit.events, dlq.skill.requests.slides | skill.requests.slides | Later |
| control-centre | approvals.decided, audit.events, dlq.approvals.requested | approvals.requested; all five dlq topics for admin view/replay | Stage 1 |
| ooh-stage-check | approvals.requested | approvals.decided, audit.events | Stage 1 (check principal only) |
| audit-writer | audit.events, dlq.skill.results, dlq.audit.events | skill.results, audit.events | Later |
| safety-watcher | approvals.requested, audit.events, dlq.skill.results | skill.results | Later |
| cost-meter | audit.events, dlq.skill.results | skill.results | Later |
| model-gateway | audit.events | none | Later |

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
short-lived check pods are removed after each check. DLQ screens and replay
remain deferred even though the Control Centre has the contracted read ACLs.

During Stage 1, device sign-in is enabled on the existing `ooh-admin-console`
client for Aziz's browser sign-in during installation checks. Access and refresh
tokens remain in shell variables and reach HTTP tools on standard input, never
on a command line or in a saved file. The check refreshes before each admin call.
Stage 4 disables device sign-in again when the Admin Console is available.
