#!/usr/bin/env bash
set -euo pipefail

echo "==> updating system packages"
sudo apt update && sudo apt upgrade -y

echo "==> installing system dependencies"
sudo apt install -y git python3-dev libusb-1.0-0-dev libopenblas-dev

echo "==> adding OAK-D udev rules"
echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", MODE="0666"' | \
  sudo tee /etc/udev/rules.d/80-movidius.rules
sudo udevadm control --reload-rules && sudo udevadm trigger

echo "==> installing uv"
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

echo "==> enabling SSH"
sudo systemctl enable ssh
sudo systemctl start ssh

echo "==> installing project dependencies"
cd "$(dirname "$0")"
uv sync

echo "==> setup complete"
