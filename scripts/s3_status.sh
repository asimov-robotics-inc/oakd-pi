#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RECORDINGS_DIR="${OAKD_RECORDINGS_DIR:-/home/pi/recordings}"
S3_BUCKET="${S3_BUCKET:-}"
S3_PREFIX="${S3_PREFIX:-uploads}"
S3_REGION="${S3_REGION:-us-east-1}"
S3_PROVIDER="${S3_PROVIDER:-AWS}"

DEVICE_ID="$("$SCRIPT_DIR/device_id.sh")"

wifi_connected() {
  if ! command -v nmcli >/dev/null 2>&1; then
    return 1
  fi
  nmcli -t -f DEVICE,TYPE,STATE dev 2>/dev/null | grep -q ":wifi:connected"
}

eth_connected() {
  if ! command -v nmcli >/dev/null 2>&1; then
    return 1
  fi
  nmcli -t -f DEVICE,TYPE,STATE dev 2>/dev/null | grep -q ":ethernet:connected"
}

if ! wifi_connected; then
  exit 0
fi

if [[ -z "$S3_BUCKET" ]]; then
  exit 0
fi

if ! command -v rclone >/dev/null 2>&1; then
  exit 0
fi

pending_dirs=0
if [[ -d "$RECORDINGS_DIR" ]]; then
  pending_dirs="$(find "$RECORDINGS_DIR" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')"
fi

wifi_state="False"
if wifi_connected; then
  wifi_state="True"
fi

eth_state="False"
if eth_connected; then
  eth_state="True"
fi

ip_addr="$(hostname -I 2>/dev/null | awk '{print $1}')"
iso_utc="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
now_ts="$(date +%s)"

recording_state="unknown"
if systemctl is-active --quiet oakd-capture 2>/dev/null; then
  recording_state="active"
else
  recording_state="inactive"
fi

tmp="/tmp/oakd-status-${DEVICE_ID}.json"
python3 - <<PY
import json
from pathlib import Path

payload = {
    "device_id": "${DEVICE_ID}",
    "hostname": "$(hostname)",
    "timestamp": int("${now_ts}"),
    "timestamp_utc": "${iso_utc}",
    "wifi_connected": ${wifi_state},
    "eth_connected": ${eth_state},
    "ip": "${ip_addr}",
    "recording_state": "${recording_state}",
    "pending_recordings": int("${pending_dirs}"),
}

Path("${tmp}").write_text(json.dumps(payload), encoding="utf-8")
PY

REMOTE_BASE=":s3:${S3_BUCKET}/${S3_PREFIX}/${DEVICE_ID}"
rclone copy \
  "$tmp" \
  "$REMOTE_BASE" \
  --s3-env-auth \
  --s3-provider "$S3_PROVIDER" \
  --s3-region "$S3_REGION" \
  --s3-no-check-bucket \
  --transfers 1 \
  --checkers 1 \
  --stats 0
