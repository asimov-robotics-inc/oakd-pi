#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> installing systemd service"
sudo cp "$SCRIPT_DIR/systemd/oakd-capture.service" /etc/systemd/system/
sudo systemctl daemon-reload

echo "==> enabling and starting oakd-capture"
sudo systemctl enable oakd-capture
sudo systemctl start oakd-capture

echo "==> oakd-capture is running"
sudo systemctl status oakd-capture --no-pager
