#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> installing systemd services"
sudo cp "$SCRIPT_DIR/systemd/oakd-capture.service" /etc/systemd/system/
sudo cp "$SCRIPT_DIR/systemd/oakd-wifi-onboard.service" /etc/systemd/system/
sudo cp "$SCRIPT_DIR/systemd/oakd-upload.service" /etc/systemd/system/
sudo cp "$SCRIPT_DIR/systemd/oakd-upload.path" /etc/systemd/system/
sudo cp "$SCRIPT_DIR/systemd/oakd-status.service" /etc/systemd/system/
sudo cp "$SCRIPT_DIR/systemd/oakd-status.timer" /etc/systemd/system/
sudo install -d /etc/NetworkManager/dispatcher.d
sudo install -m 755 "$SCRIPT_DIR/systemd/NetworkManager/dispatcher.d/90-oakd-upload" /etc/NetworkManager/dispatcher.d/90-oakd-upload
sudo rm -f /etc/NetworkManager/dnsmasq.d/oakd-captive.conf
sudo systemctl daemon-reload

echo "==> enabling and starting services"
sudo systemctl enable oakd-capture
sudo systemctl start oakd-capture
sudo systemctl enable oakd-wifi-onboard
sudo systemctl start oakd-wifi-onboard
sudo systemctl enable oakd-upload.path
sudo systemctl start oakd-upload.path
sudo systemctl enable oakd-status.timer
sudo systemctl start oakd-status.timer

echo "==> oakd-capture is running"
sudo systemctl status oakd-capture --no-pager
