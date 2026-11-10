#!/usr/bin/env bash
# Installs CrowdCast Screen Sentinel as a systemd user service
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICE_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$SERVICE_DIR/crowdcast-sentinel.service"

mkdir -p "$SERVICE_DIR"

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=CrowdCast Screen Sentinel & Blackout Resolver
After=network.target

[Service]
Type=simple
WorkingDirectory=$REPO_ROOT
ExecStart=/usr/bin/python3 $REPO_ROOT/sentinel.py serve --host 0.0.0.0 --port 8585
Restart=on-failure
RestartSec=5s
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
echo "✅ Installed systemd service to $SERVICE_FILE"
echo "To enable and start now, run:"
echo "  systemctl --user enable --now crowdcast-sentinel.service"
