# QUICK GUIDE

1. Type this in your harness terminal, in the plain shell. This runs all contract
   checks from the Part A folder. No password is needed. Good result: 2 passed.

   ```bash
   cd ~/projects/worktrees/stage-0-part-a
   uv run --project contracts/check pytest
   ```

2. Type this in your harness terminal, in the plain shell. This checks Python
   style. No password is needed. Good result: All checks passed.

   ```bash
   cd ~/projects/worktrees/stage-0-part-a/contracts/check
   uv run ruff check
   ```

3. Type this in your harness terminal, in the plain shell. This checks formatting.
   No password is needed. Good result: 2 files already formatted.

   ```bash
   cd ~/projects/worktrees/stage-0-part-a/contracts/check
   uv run ruff format --check
   ```

4. Type this in your harness terminal, in the plain shell. This prints the number
   of validated contracts as JSON. No password is needed. Good result: passed.

   ```bash
   cd ~/projects/worktrees/stage-0-part-a
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
JSON syntax, which is valid YAML. JSON Schemas carry the SPDX identifier in
$comment because JSON cannot contain comment lines. Examples are synthetic data,
not source code. No real model details, credentials or personal data are examples.

SSE response schemas describe the JSON inside each data field; records are
separated by a blank line. Gateway stream=false returns JSON; stream=true returns
SSE. Error responses use code/message. Classification scores range from 0 to 1
and are suggestions. Runtime registry identifiers are opaque; no deployment
model choices are fixed here. Query/path inputs are declared as parameters.

The smoke topic carries audit.event envelopes for platform checks. DLQ payloads
retain the original serialized record and error, including malformed inputs.
DLQ records themselves still use the common envelope. Kafka keys equal
correlation_id. Consumers ignore handled event_id values, retry a fixed number
of times, then emit the DLQ record. Consumer retry settings arrive with workers.

## Versioning

A breaking change creates a new version. Keep the old version until nobody uses
it. Envelope version is an integer; manifest version is semantic versioning.
Never silently replace a live contract with an incompatible shape. Changes to
contracts and their examples are reviewed together before implementation.
