#!/usr/bin/env bash
# Quick launcher for CrowdCast Screen Sentinel Web Dashboard
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

HOST="${SENTINEL_HOST:-0.0.0.0}"
PORT="${SENTINEL_PORT:-8585}"

echo "=========================================================="
echo "🛡️  Starting CrowdCast Screen Sentinel Dashboard"
echo "👉 Local Web Dashboard: http://localhost:${PORT}"
echo "👉 Network/VM Access   : http://10.5.48.1:${PORT}"
echo "=========================================================="

cd "$REPO_ROOT"
exec /usr/bin/python3 sentinel.py serve --host "$HOST" --port "$PORT"
