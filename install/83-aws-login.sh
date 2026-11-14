#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
# shellcheck source=install/81-aws-bootstrap.sh
source "$(dirname "${BASH_SOURCE[0]}")/81-aws-bootstrap.sh"
aws_setup
printf '%s\n' 'Claude opens the link AWS prints; Aziz approves in the browser, copies the code AWS shows and pastes it here (the only thing he pastes). No Codex builder may run during this AWS work block.'
aws login --remote
check_signin
save_setting AWS_SIGNIN_AT "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf 'DONE\n'
