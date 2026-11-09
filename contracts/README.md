# QUICK GUIDE

1. Type this in your harness terminal, in the plain shell. This runs all contract
   checks from the repository root. No password is needed. Good result: all tests pass.

   ```bash
   cd ~/projects/open-office-harness
   uv run --project contracts/check pytest
   ```

2. Type this in your harness terminal, in the plain shell. This checks Python
   style. No password is needed. Good result: All checks passed.

   ```bash
   cd ~/projects/open-office-harness
   uv run --project contracts/check ruff check contracts/check
   ```

3. Type this in your harness terminal, in the plain shell. This checks formatting.
   No password is needed. Good result: 2 files already formatted.

   ```bash
   cd ~/projects/open-office-harness
   uv run --project contracts/check ruff format --check contracts/check
   ```

4. Type this in your harness terminal, in the plain shell. This prints the number
   of validated contracts as JSON. No password is needed. Good result: passed.

   ```bash
   cd ~/projects/open-office-harness
   uv run --project contracts/check python contracts/check/check_contracts.py
   ```

These are file checks; there is no service to start, stop, restart or deploy.
After reboot, run the same checks. Results appear in the terminal; no log file
is written. If a check fails, read its file and validation error, correct the
contract and example together, and run it again. No STOP messages are generated
by these checks. Platform operations are covered by the root README.

## Files

| Path | Agreement |
|---|---|
| identity.md | OIDC clients, claims, service accounts, Kafka access |
| storage.md | Private object keys and signed downloads |
| http/control-centre.openapi.yaml | Rights, allowed skills, purpose/tier registry |
| http/model-gateway.openapi.yaml | Purpose calls and classification |
| http/harness-api.openapi.yaml | Conversations, SSE, uploads and links |
| events/envelope.schema.json | Common event fields and payload selection |
| events/payloads/*.schema.json | Six event payload types |
| events/topics.yaml | Partitions, retention, producers and consumers |
| skills/manifest.schema.json | Worker/instruction manifest format |
| skills/slides/manifest.json | Registered Slides skill |
| skills/slides/input.schema.json | Slides request |
| skills/slides/output.schema.json | Slides output file reference |
| examples/index.json | Maps each example to its schema or HTTP body |
| examples/events, examples/skills, examples/http | Synthetic valid examples |
| check/pyproject.toml, check/uv.lock | Python 3.14 check project and exact dependency versions |
| check/check_contracts.py | Schema, reference, OpenAPI, example and topic validation |
| check/tests/test_contracts.py | Positive checks and deliberately invalid payload rejection |

JSON Schemas use draft 2020-12; HTTP contracts use OpenAPI 3.1. YAML files use
block-style YAML. JSON Schemas carry the SPDX identifier in
$comment because JSON cannot contain comment lines. Examples are synthetic data,
not source code. No real model details, credentials or personal data are examples.

SSE response schemas describe the JSON inside each data field; records are
separated by a blank line. Gateway stream=false returns JSON; stream=true returns
SSE. Error responses use code/message. Classification scores range from 0 to 1
and are suggestions. Registry replies describe runtime provider assignments, including endpoint_url,
model_id and secret_ref (the name of a Kubernetes Secret key, never its value).
No deployment model choices are fixed here. tier is required for chat registry
lookups and omitted for other purposes. Query/path inputs are declared as parameters.
OpenAPI declares purpose and tier as separate query parameters, so this dependency
is expressed in the operation description rather than a cross-parameter schema.
The checker enforces it through the /api/models special case in
validate_parameters; generic OpenAPI parameter validators alone do not enforce it.

The ooh.smoke topic carries free-form test messages for platform checks only.
It has no schema or envelope; the checker explicitly exempts it from payload
schema validation. Business-event topics use the common envelope. DLQ payloads
retain the original serialized record and error, including malformed inputs.
DLQ records themselves still use the common envelope. Business-event Kafka keys equal
correlation_id. Consumers ignore handled event_id values, retry a fixed number
of times, then emit the DLQ record. Consumer retry settings arrive with workers.

## Versioning

A breaking change creates a new version. Keep the old version until nobody uses
it. Envelope version is an integer; manifest version is semantic versioning.
Never silently replace a live contract with an incompatible shape. Changes to
contracts and their examples are reviewed together before implementation.

## Generic skill events and file requests

skill.requested declares skill, skill_version and an input object. The worker
validates input against contracts/skills/<skill>/input.schema.json; adding a skill
does not change the generic event schema. skill.result and Harness job updates
use generic skill names, nullable output/error and unrestricted MIME strings.
oneOf branches require an output object and null error for completed results,
an error object and null output for failed results, and null output/error for
queued or awaiting-approval job updates. Only the Slides contracts constrain the
output to PowerPoint.

POST /api/uploads accepts multipart/form-data with a binary file field. Its JSON
example represents the decoded file part's synthetic bytes as a string; clients
send an actual multipart file part, not a JSON request. Success returns file_key.
Message and file lookups declare 404 when the resource does not exist.

OpenAPI errors are defined once per document as components/schemas/Error and
referenced with JSON pointers. Responses without content (such as 204) need no
body example. The checker uses explicit errors even when Python optimization
is enabled.

Registry endpoint_url and signed-download url retain format: uri and also require
an HTTP(S) URL pattern with a nonempty authority and no whitespace. This pattern
is checked without optional URI-validation packages or new dependencies.
