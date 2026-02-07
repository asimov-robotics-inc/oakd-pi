#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -n "${S3_DEVICE_ID:-}" ]]; then
  echo "${S3_DEVICE_ID// /_}"
  exit 0
fi

serial=""
if [[ -r /proc/cpuinfo ]]; then
  serial="$(awk -F': ' '/Serial/ {print $2}' /proc/cpuinfo | tail -n 1 | tr -d '[:space:]')"
fi
if [[ -z "$serial" && -r /sys/firmware/devicetree/base/serial-number ]]; then
  serial="$(tr -d '\0[:space:]' < /sys/firmware/devicetree/base/serial-number)"
fi

map_path="${DEVICE_MAP_PATH:-}"
if [[ -z "$map_path" && -r "${SCRIPT_DIR}/../config/device_map.json" ]]; then
  map_path="${SCRIPT_DIR}/../config/device_map.json"
fi
if [[ -z "$map_path" && -r /etc/oakd/device_map.json ]]; then
  map_path="/etc/oakd/device_map.json"
fi

if [[ -n "$serial" && -n "$map_path" && -r "$map_path" ]]; then
  mapped="$(MAP_PATH="$map_path" DEVICE_SERIAL="$serial" python3 - <<PY
import json
import os
import sys

path = os.environ.get("MAP_PATH")
serial = os.environ.get("DEVICE_SERIAL")
if not path or not serial:
    sys.exit(1)
try:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    sys.exit(1)
value = data.get(serial, "")
if not isinstance(value, str):
    value = ""
sys.stdout.write(value)
PY
)"
  if [[ -n "$mapped" ]]; then
    echo "${mapped// /_}"
    exit 0
  fi
fi

if [[ -r /etc/oakd/device_id ]]; then
  DEVICE_ID="$(tr -d '\n' < /etc/oakd/device_id)"
  echo "${DEVICE_ID// /_}"
  exit 0
fi

DEVICE_ID="$(hostname)"
if [[ "$DEVICE_ID" == "raspberrypi" && -r /etc/machine-id ]]; then
  short_id="$(tr -d '\n' < /etc/machine-id | cut -c1-8)"
  DEVICE_ID="oakd-${short_id}"
fi
echo "${DEVICE_ID// /_}"
