#!/usr/bin/env bash
set -euo pipefail

echo "==> stopping oakd-capture"
sudo systemctl stop oakd-capture

echo "==> disabling oakd-capture from boot"
sudo systemctl disable oakd-capture

echo "==> oakd-capture stopped and disabled"
