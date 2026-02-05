#!/usr/bin/env bash
set -euo pipefail

echo "==> stopping services"
sudo systemctl stop oakd-capture || true
sudo systemctl stop oakd-wifi-onboard || true
sudo systemctl stop oakd-upload.path || true

echo "==> disabling services from boot"
sudo systemctl disable oakd-capture || true
sudo systemctl disable oakd-wifi-onboard || true
sudo systemctl disable oakd-upload.path || true

echo "==> services stopped and disabled"
