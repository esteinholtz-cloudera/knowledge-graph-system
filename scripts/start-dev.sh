#!/usr/bin/env bash
# Start API and GUI dev servers (ports from config/config.yaml).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
exec uv run python scripts/start_dev.py "$@"
