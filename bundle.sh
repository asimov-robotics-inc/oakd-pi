#!/usr/bin/env bash
set -euo pipefail

# bundle.sh — run on a configured Pi to create a deployable tarball
# Output: oakd-capture-bundle.tar.gz (~60-80MB)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUNDLE_NAME="oakd-capture-bundle"
BUNDLE_TAR="${SCRIPT_DIR}/${BUNDLE_NAME}.tar.gz"

echo "==> verifying this is running on aarch64"
ARCH="$(uname -m)"
if [[ "$ARCH" != "aarch64" ]]; then
    echo "error: bundle must be created on aarch64 (got ${ARCH})"
    echo "the .venv is only portable between identical architectures"
    exit 1
fi

echo "==> verifying .venv exists"
if [[ ! -d "${SCRIPT_DIR}/.venv" ]]; then
    echo "error: .venv not found — run setup.sh first"
    exit 1
fi

echo "==> creating staging directory"
STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

DEST="${STAGING}/${BUNDLE_NAME}"
mkdir -p "$DEST"

echo "==> copying source code"
cp -r "${SCRIPT_DIR}/src" "$DEST/"
cp "${SCRIPT_DIR}/pyproject.toml" "$DEST/"
cp "${SCRIPT_DIR}/.python-version" "$DEST/"

echo "==> copying systemd service"
cp -r "${SCRIPT_DIR}/systemd" "$DEST/"

echo "==> copying .venv"
cp -a "${SCRIPT_DIR}/.venv" "$DEST/"

echo "==> writing install.sh"
cat > "${DEST}/install.sh" << 'INSTALL_EOF'
#!/usr/bin/env bash
set -euo pipefail

# install.sh — first-time setup on a fresh Pi
# Embedded in the bundle tarball, run automatically by deploy.sh

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
OAKD_USER="${OAKD_USER:-pi}"
OAKD_HOME="/home/${OAKD_USER}/oakd-pi"

echo "==> checking Python version"
PY_VERSION="$(python3 --version 2>/dev/null || true)"
if [[ -z "$PY_VERSION" ]]; then
    echo "error: python3 not found"
    exit 1
fi
PY_MINOR="$(python3 -c 'import sys; print(sys.version_info.minor)')"
if [[ "$PY_MINOR" -ne 11 ]]; then
    echo "warning: expected Python 3.11 but found ${PY_VERSION}"
    echo "the bundled .venv may not work correctly"
fi

echo "==> installing system dependencies"
sudo apt update -qq
sudo apt install -y libusb-1.0-0-dev libopenblas-dev

echo "==> writing OAK-D udev rule"
echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", MODE="0666"' | \
    sudo tee /etc/udev/rules.d/80-movidius.rules > /dev/null
sudo udevadm control --reload-rules && sudo udevadm trigger

echo "==> deploying to ${OAKD_HOME}"
sudo mkdir -p "$OAKD_HOME"
sudo cp -a "${INSTALL_DIR}/src" "$OAKD_HOME/"
sudo cp -a "${INSTALL_DIR}/.venv" "$OAKD_HOME/"
sudo cp "${INSTALL_DIR}/pyproject.toml" "$OAKD_HOME/"
sudo cp "${INSTALL_DIR}/.python-version" "$OAKD_HOME/"
sudo mkdir -p "$OAKD_HOME/systemd"
sudo cp "${INSTALL_DIR}/systemd/oakd-capture.service" "$OAKD_HOME/systemd/"
sudo chown -R "${OAKD_USER}:${OAKD_USER}" "$OAKD_HOME"

echo "==> installing systemd service"
sudo cp "${INSTALL_DIR}/systemd/oakd-capture.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable oakd-capture
sudo systemctl start oakd-capture

echo "==> install complete"
sudo systemctl status oakd-capture --no-pager || true
INSTALL_EOF
chmod +x "${DEST}/install.sh"

echo "==> creating tarball"
tar -czf "$BUNDLE_TAR" -C "$STAGING" "$BUNDLE_NAME"

SIZE="$(du -h "$BUNDLE_TAR" | cut -f1)"
echo "==> bundle created: ${BUNDLE_TAR} (${SIZE})"
