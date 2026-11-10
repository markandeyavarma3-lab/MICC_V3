#!/usr/bin/env bash
# setup_server.sh: prepare a fresh Oracle Cloud server (Ubuntu 24.04, ARM) for the
# project. Run ON the server, once, as the default user:
#
#     bash setup_server.sh
#
# Safe to run again: each step checks before it acts.
#
# What it does:
#   1. security updates now, and automatically from then on
#   2. logins by key only (Oracle's image already does this; made certain here)
#   3. an 8 GB swap file, so a large DuckDB query slows down instead of failing
#      on a 12 GB machine
#   4. Python 3.14 through uv, the project's exact pinned packages
#   5. Node 20 for the website build (Ubuntu's own Node is 18, too old for Astro 5)
#
# Layout on the server (no spaces, no hyphens):
#   ~/micc/research   the research repo, cloned from GitHub; data/ and db/ are copied
#                     in from the laptop by cloud/sync_up.sh
#   ~/micc/website    the website, copied from the laptop (it has no GitHub remote)
#
# Nothing here holds a password or key. The repo is public.

set -euo pipefail

UV_VERSION="0.11.28"
NODE_VERSION="20.20.2"
REPO_URL="https://github.com/markandeyavarma3-lab/MICC_V3.git"
HOME_DIR="$HOME/micc"

say() { printf '\n== %s\n' "$*"; }

say "1. updates"
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y git rsync unattended-upgrades sqlite3 curl xz-utils
sudo dpkg-reconfigure -f noninteractive unattended-upgrades

say "2. logins by key only"
if sudo grep -qE '^\s*PasswordAuthentication\s+yes' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null; then
  echo "PasswordAuthentication no" | sudo tee /etc/ssh/sshd_config.d/00_keys_only.conf >/dev/null
  sudo sshd -t && sudo systemctl reload ssh
fi
sudo sshd -T 2>/dev/null | grep -E '^passwordauthentication' || true

say "3. swap"
if ! sudo swapon --show | grep -q /swapfile; then
  sudo fallocate -l 8G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile >/dev/null
  sudo swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi
free -g | head -3

say "4. Python and the project"
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null || [ "$(uv --version | awk '{print $2}')" != "$UV_VERSION" ]; then
  curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" | sh
fi
uv python install 3.14
mkdir -p "$HOME_DIR"
if [ ! -d "$HOME_DIR/research/.git" ]; then
  git clone "$REPO_URL" "$HOME_DIR/research"
else
  git -C "$HOME_DIR/research" pull --ff-only
fi
cd "$HOME_DIR/research"
[ -x .venv/bin/python ] || uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -e '.[dev]'
mkdir -p data db logs

say "5. Node for the website"
if ! "$HOME/.local/node/bin/node" --version 2>/dev/null | grep -q "v$NODE_VERSION"; then
  tmp="$(mktemp -d)"
  curl -fsSL "https://nodejs.org/dist/v$NODE_VERSION/node-v$NODE_VERSION-linux-arm64.tar.xz" -o "$tmp/node.tar.xz"
  rm -rf "$HOME/.local/node" && mkdir -p "$HOME/.local/node"
  tar -xJf "$tmp/node.tar.xz" -C "$HOME/.local/node" --strip-components=1
  rm -rf "$tmp"
fi
grep -q '.local/node/bin' "$HOME/.profile" 2>/dev/null \
  || echo 'export PATH="$HOME/.local/node/bin:$HOME/.local/bin:$PATH"' >> "$HOME/.profile"
mkdir -p "$HOME_DIR/website"

say "done"
echo "python: $("$HOME_DIR/research/.venv/bin/python" --version)"
echo "duckdb: $("$HOME_DIR/research/.venv/bin/python" -c 'import duckdb; print(duckdb.__version__)')"
echo "node:   $("$HOME/.local/node/bin/node" --version)"
echo "disk:   $(df -h "$HOME" | awk 'NR==2 {print $4 " free of " $2}')"
echo "next: on the laptop, run cloud/sync_up.sh to copy the data in"
