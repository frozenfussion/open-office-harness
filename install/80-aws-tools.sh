#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
set -E
umask 077
export PATH="$HOME/.local/bin:$PATH"
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
trap 'stop "tool installation failed; fix the reported error and rerun install/80-aws-tools.sh"' ERR
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || stop 'these pinned tools require Linux x86_64'
for tool in curl python3 sha256sum; do command -v "$tool" >/dev/null || stop "install $tool first"; done
install -d -m 700 "$HOME/.cache/ooh"
install -d "$HOME/.local/bin"
work=$(mktemp -d "$HOME/.cache/ooh/tools.XXXXXX")
trap 'rm -rf "$work"' EXIT
fetch() { curl --fail --silent --show-error --location --retry 3 "$1" -o "$work/$2"; }
extract() { python3 -m zipfile -e "$work/$1" "$work/$2"; }
fetch https://awscli.amazonaws.com/awscli-exe-linux-x86_64-2.40.3.zip aws.zip
# SHA256 of the versioned official AWS artifact, checked 2026-11-14.
printf '%s  %s\n' 4770c06c4ecfc8ba94b60d89e6c7018ab7ea2cf5341b1ef05f6f93c5d6e8b705 "$work/aws.zip" | sha256sum -c -
extract aws.zip aws-extract
chmod -R u+x "$work/aws-extract/aws"
"$work/aws-extract/aws/install" --install-dir "$HOME/.local/aws-cli" --bin-dir "$HOME/.local/bin" --update
fetch https://releases.hashicorp.com/terraform/1.17.2/terraform_1.17.2_linux_amd64.zip terraform.zip
fetch https://releases.hashicorp.com/terraform/1.17.2/terraform_1.17.2_SHA256SUMS terraform.sums
expected=$(awk '$2 == "terraform_1.17.2_linux_amd64.zip" {print $1}' "$work/terraform.sums")
[[ $expected =~ ^[a-f0-9]{64}$ ]] || stop 'Terraform checksum missing'
printf '%s  %s\n' "$expected" "$work/terraform.zip" | sha256sum -c -
extract terraform.zip terraform
install -m 755 "$work/terraform/terraform" "$HOME/.local/bin/terraform"
fetch https://github.com/terraform-linters/tflint/releases/download/v0.66.0/tflint_linux_amd64.zip tflint.zip
fetch https://github.com/terraform-linters/tflint/releases/download/v0.66.0/checksums.txt tflint.sums
expected=$(awk '$2 == "tflint_linux_amd64.zip" {print $1}' "$work/tflint.sums")
[[ $expected =~ ^[a-f0-9]{64}$ ]] || stop 'TFLint checksum missing'
printf '%s  %s\n' "$expected" "$work/tflint.zip" | sha256sum -c -
extract tflint.zip tflint
install -m 755 "$work/tflint/tflint" "$HOME/.local/bin/tflint"
for root in bootstrap cluster addons; do (cd "$ROOT/infra/terraform/aws/$root" && tflint --init); done
# Keep the login shell variables literal in the profile.
# shellcheck disable=SC2016
profile_line='export PATH="$HOME/.local/bin:$PATH"'
if [[ ! -f $HOME/.profile ]] || ! python3 - "$HOME/.profile" "$profile_line" <<'PY'
import pathlib,sys
sys.exit(0 if sys.argv[2] in pathlib.Path(sys.argv[1]).read_text().splitlines() else 1)
PY
then printf '\n%s\n' "$profile_line" >> "$HOME/.profile"; fi
terraform version
# Never contact an AWS account from the tool installer.
tflint --version
printf 'DONE\n'
