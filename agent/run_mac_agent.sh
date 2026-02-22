#!/usr/bin/env bash
# Run Mac agent poller. Set env vars before calling.
# Example:
#   export RAILWAY_URL=... UI_AGENT_TOKEN=... LOCAL_UI_EXECUTOR_URL=... LOCAL_UI_EXECUTOR_TOKEN=...
#   ./agent/run_mac_agent.sh

set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
python3 agent/mac_agent_poll.py
