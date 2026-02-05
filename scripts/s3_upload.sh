#!/usr/bin/env bash
set -euo pipefail

RECORDINGS_DIR="${OAKD_RECORDINGS_DIR:-/home/pi/recordings}"
S3_BUCKET="${S3_BUCKET:-}"
S3_PREFIX="${S3_PREFIX:-oakd-recordings}"
S3_REGION="${S3_REGION:-us-east-1}"
if [[ -n "${S3_DEVICE_ID:-}" ]]; then
  DEVICE_ID="$S3_DEVICE_ID"
else
  DEVICE_ID="$(hostname)"
  if [[ "$DEVICE_ID" == "raspberrypi" && -r /etc/machine-id ]]; then
    DEVICE_ID="$(tr -d '\n' < /etc/machine-id)"
  fi
fi
DEVICE_ID="${DEVICE_ID// /_}"

log() {
  echo "[s3-upload] $*"
}

wifi_connected() {
  if ! command -v nmcli >/dev/null 2>&1; then
    return 1
  fi
  nmcli -t -f DEVICE,TYPE,STATE dev 2>/dev/null | grep -q ":wifi:connected"
}

if ! wifi_connected; then
  log "Wi-Fi not connected; skipping upload"
  exit 0
fi

if [[ -z "$S3_BUCKET" ]]; then
  log "S3_BUCKET not set; skipping upload"
  exit 0
fi

if ! command -v rclone >/dev/null 2>&1; then
  log "rclone not installed; skipping upload"
  exit 0
fi

exec 9>/tmp/oakd-upload.lock
if ! flock -n 9; then
  log "Uploader already running; exiting"
  exit 0
fi

REMOTE_BASE=":s3:${S3_BUCKET}/${S3_PREFIX}/${DEVICE_ID}"

shopt -s nullglob
for dir in "$RECORDINGS_DIR"/*; do
  if [[ ! -d "$dir" ]]; then
    continue
  fi
  if [[ ! -f "$dir/.done" ]]; then
    continue
  fi

  base="$(basename "$dir")"
  log "Uploading $base to $REMOTE_BASE/$base/"

  rclone move \
    "$dir" \
    "$REMOTE_BASE/$base" \
    --s3-env-auth \
    --s3-region "$S3_REGION" \
    --transfers 2 \
    --checkers 4 \
    --stats 1m

  if [[ -d "$dir" ]]; then
    rmdir "$dir" 2>/dev/null || true
  fi
  log "Uploaded and removed $base"
done
