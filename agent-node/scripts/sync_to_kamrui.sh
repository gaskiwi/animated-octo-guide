#!/bin/bash
# Sync the local agent-node mirror to kamrui WITHOUT touching .env.
# The .env clobber has broken auth twice — keep these excludes.
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
rsync -av \
  --exclude='.env' --exclude='.env.*' \
  --exclude='__pycache__/' --exclude='*.pyc' \
  --exclude='state/' --exclude='workspace/' --exclude='logs/' \
  --exclude='.openclaw/' \
  "$SRC/" kamrui:~/animated-octo-guide/agent-node/
echo "Synced. Rebuild on kamrui: ssh kamrui 'cd ~/animated-octo-guide/agent-node && docker compose build && docker compose up -d'"
