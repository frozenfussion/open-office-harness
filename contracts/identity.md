# Identity contract v1

Issuer: https://auth.faysalaziz.com/realms/ooh. Realm: `ooh`.
Realm roles: `ooh-admin`, `ooh-user`. Self-registration is off; later sign-ups
use approvals. Brute-force protection is on. Access tokens last five minutes.

| Client | Type | Use |
|---|---|---|
| ooh-workspace | Public, authorization code with PKCE S256 | Workspace; redirect URIs on https://harness.faysalaziz.com only |
| ooh-admin-console | Public, authorization code with PKCE S256 | Admin Console; redirect URIs on https://admin.faysalaziz.com only |
| ooh-harness-api | Confidential, service accounts | Harness service-to-service client credentials |
| ooh-control-centre | Confidential, service accounts | Control Centre service-to-service client credentials |

UIs send bearer access tokens. Each receiving service validates the signature
using the realm public keys, issuer, expiry and intended audience. `sub` is
`user_id`; `realm_access.roles` supplies realm roles. Service-to-service calls
use client credentials, never user passwords. A user_id parameter is subject to
authorization against the authenticated identity; supplying another user's ID
never grants access. Health is the only unauthenticated HTTP route.

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
| control-centre | approvals.decided, audit.events, dlq.approvals.requested | approvals.requested; all five dlq topics for admin view/replay | Later |
| audit-writer | audit.events, dlq.skill.results, dlq.audit.events | skill.results, audit.events | Later |
| safety-watcher | approvals.requested, audit.events, dlq.skill.results | skill.results | Later |
| cost-meter | audit.events, dlq.skill.results | skill.results | Later |
| model-gateway | audit.events | none | Later |

Every service may emit audit events. Each consumer may write the corresponding
DLQ after its fixed retry limit. The Admin Console accesses DLQ view/replay
through the Control Centre; browser clients never get Kafka credentials. Replay
permissions and routes are deferred to their stage; no broad producer rights
are granted here. Safety watcher may raise an approval request, never a skill
job. The `ooh-smoke` principal must be refused writes to `skill.results`.
