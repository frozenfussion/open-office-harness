#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# One-time setup of the Droplet ooh-01. Aziz runs it:  sudo install/01-server-setup.sh
# Re-runnable: every step checks first and skips what is already done.
# Written by the spec author for Stage 0. Codex does not change this file.
set -euo pipefail

K3S_VERSION="v1.36.6+k3s1"
NODE_MAJOR="26"
KUBECONFORM_VERSION="v0.8.0"
UV_VERSION="0.13.7"

say()  { printf '\n== %s\n' "$*"; }
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || stop "run this with sudo: sudo install/01-server-setup.sh"
TARGET_USER="${SUDO_USER:-}"
[[ -n "$TARGET_USER" && "$TARGET_USER" != "root" ]] || stop "run it as your own user with sudo, not as root (expected user: aziz)"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

# shellcheck source=/dev/null
. /etc/os-release
[[ "${ID:-}" == "ubuntu" && "${VERSION_ID:-}" == "24.04" ]] || stop "this script expects Ubuntu 24.04, found ${PRETTY_NAME:-unknown}"

say "1/7 Base packages"
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y git curl jq ca-certificates gnupg unzip shellcheck

say "2/7 GitHub CLI (gh) from GitHub's apt repository"
if [[ ! -f /etc/apt/sources.list.d/github-cli.list ]]; then
  install -d -m 0755 /etc/apt/keyrings
  curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg -o /etc/apt/keyrings/githubcli-archive-keyring.gpg
  chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list
  apt-get update -y
fi
DEBIAN_FRONTEND=noninteractive apt-get install -y gh

say "3/7 Node.js ${NODE_MAJOR}.x from NodeSource (needed for the Codex CLI and, later, Angular)"
if [[ ! -f /etc/apt/sources.list.d/nodesource.list ]]; then
  curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
  echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" > /etc/apt/sources.list.d/nodesource.list
  apt-get update -y
fi
DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs
node_version="$(node --version)"
[[ "$node_version" == v${NODE_MAJOR}.* ]] || stop "node is $node_version, expected v${NODE_MAJOR}.x"

say "4/7 k3s ${K3S_VERSION}"
current_k3s=""
if command -v k3s >/dev/null 2>&1; then
  current_k3s="$(k3s --version)"
fi
if [[ "$current_k3s" != *"${K3S_VERSION}"* ]]; then
  curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="${K3S_VERSION}" sh -s - server --write-kubeconfig-mode 0600
fi
for _ in $(seq 1 60); do
  if k3s kubectl get nodes >/dev/null 2>&1; then break; fi
  sleep 2
done
nodes="$(k3s kubectl get nodes --no-headers 2>/dev/null || true)"
[[ "$nodes" == *" Ready "* ]] || stop "k3s node is not Ready yet; check: sudo systemctl status k3s"

say "5/7 kubectl access for ${TARGET_USER}"
install -d -m 0700 -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.kube"
install -m 0600 -o "$TARGET_USER" -g "$TARGET_USER" /etc/rancher/k3s/k3s.yaml "$TARGET_HOME/.kube/config"
# shellcheck disable=SC2016  # written literally into .bashrc on purpose
profile_line='export KUBECONFIG="$HOME/.kube/config"'
bashrc="$TARGET_HOME/.bashrc"
bashrc_text="$(cat "$bashrc" 2>/dev/null || true)"
if [[ "$bashrc_text" != *"$profile_line"* ]]; then
  echo "$profile_line" >> "$bashrc"
  chown "$TARGET_USER:$TARGET_USER" "$bashrc"
fi

say "6/7 kubeconform ${KUBECONFORM_VERSION} and uv ${UV_VERSION}"
current_kc="$(/usr/local/bin/kubeconform -v 2>/dev/null || true)"
if [[ "$current_kc" != "${KUBECONFORM_VERSION}" ]]; then
  tmp="$(mktemp -d)"
  curl -fsSL "https://github.com/yannh/kubeconform/releases/download/${KUBECONFORM_VERSION}/kubeconform-linux-amd64.tar.gz" -o "$tmp/kc.tgz"
  tar -xzf "$tmp/kc.tgz" -C "$tmp" kubeconform
  install -m 0755 "$tmp/kubeconform" /usr/local/bin/kubeconform
  rm -rf "$tmp"
fi
current_uv="$(/usr/local/bin/uv --version 2>/dev/null || true)"
if [[ "$current_uv" != "uv ${UV_VERSION}"* ]]; then
  curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
fi

say "7/7 Projects folder"
install -d -m 0755 -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/projects"

say "Versions"
echo "k3s:         $(k3s --version | sed -n 1p)"
echo "node:        $(node --version)"
echo "gh:          $(gh --version | sed -n 1p)"
echo "kubeconform: $(/usr/local/bin/kubeconform -v)"
echo "uv:          $(/usr/local/bin/uv --version)"
k3s kubectl get nodes
echo "DONE"
