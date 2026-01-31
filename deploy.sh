#!/usr/bin/env bash
set -euo pipefail

# deploy.sh — deploy oakd-capture to a Pi from your dev machine
#
# Usage:
#   ./deploy.sh <host>            # First deploy: SCP bundle, extract, run install.sh
#   ./deploy.sh <host> --update   # Fast update: rsync source only, restart service
#
# Environment:
#   OAKD_USER  - SSH user on target Pi (default: pi)
#   BUNDLE     - Path to bundle tarball (default: ./oakd-capture-bundle.tar.gz)

usage() {
    echo "usage: $0 <host> [--update]"
    echo ""
    echo "  <host>      hostname or IP of the target Pi"
    echo "  --update    fast source-only update (skip full install)"
    echo ""
    echo "environment:"
    echo "  OAKD_USER   SSH user (default: pi)"
    echo "  BUNDLE      path to tarball (default: ./oakd-capture-bundle.tar.gz)"
    exit 1
}

[[ $# -lt 1 ]] && usage

HOST="$1"
MODE="${2:-full}"
OAKD_USER="${OAKD_USER:-pi}"
REMOTE_DIR="/home/${OAKD_USER}/oakd-pi"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUNDLE="${BUNDLE:-${SCRIPT_DIR}/oakd-capture-bundle.tar.gz}"

if [[ "$MODE" != "full" && "$MODE" != "--update" ]]; then
    usage
fi

echo "==> testing SSH connectivity to ${OAKD_USER}@${HOST}"
if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "${OAKD_USER}@${HOST}" true 2>/dev/null; then
    echo "error: cannot SSH to ${OAKD_USER}@${HOST}"
    echo "ensure SSH key auth is configured and the Pi is reachable"
    exit 1
fi

if [[ "$MODE" == "--update" ]]; then
    echo "==> syncing source code to ${HOST}"
    rsync -az --delete \
        "${SCRIPT_DIR}/src/" \
        "${OAKD_USER}@${HOST}:${REMOTE_DIR}/src/"

    echo "==> restarting oakd-capture service"
    ssh "${OAKD_USER}@${HOST}" "sudo systemctl restart oakd-capture"

    echo "==> update complete"
    ssh "${OAKD_USER}@${HOST}" "sudo systemctl status oakd-capture --no-pager" || true
    exit 0
fi

# --- Full deploy ---

if [[ ! -f "$BUNDLE" ]]; then
    echo "error: bundle not found at ${BUNDLE}"
    echo "run bundle.sh on a configured Pi first, then copy the tarball here"
    exit 1
fi

SIZE="$(du -h "$BUNDLE" | cut -f1)"
echo "==> uploading bundle (${SIZE}) to ${HOST}"
scp "$BUNDLE" "${OAKD_USER}@${HOST}:/tmp/oakd-capture-bundle.tar.gz"

echo "==> extracting bundle on ${HOST}"
ssh "${OAKD_USER}@${HOST}" "cd /tmp && tar -xzf oakd-capture-bundle.tar.gz"

echo "==> running install.sh on ${HOST}"
ssh "${OAKD_USER}@${HOST}" "cd /tmp/oakd-capture-bundle && sudo OAKD_USER=${OAKD_USER} bash install.sh"

echo "==> cleaning up"
ssh "${OAKD_USER}@${HOST}" "rm -rf /tmp/oakd-capture-bundle /tmp/oakd-capture-bundle.tar.gz"

echo "==> deploy complete"
