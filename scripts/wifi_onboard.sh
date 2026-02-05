#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

TIMEOUT_S="${WIFI_ONBOARD_TIMEOUT_S:-300}"
HOTSPOT_SSID="${WIFI_HOTSPOT_SSID:-recording-device-setup}"
HOTSPOT_PASS="${WIFI_HOTSPOT_PASS:-}"
HOTSPOT_IFACE="${WIFI_HOTSPOT_IFACE:-wlan0}"
PORTAL_PORT="${WIFI_PORTAL_PORT:-80}"

log() {
  echo "[wifi-onboard] $*"
}

have_nmcli() {
  command -v nmcli >/dev/null 2>&1
}

active_wifi_conn() {
  nmcli -t -f NAME,TYPE,DEVICE con show --active 2>/dev/null | awk -F: '$2=="802-11-wireless" {print $1; exit}'
}

wifi_connected() {
  local conn
  conn="$(active_wifi_conn)"
  if [[ -z "$conn" ]]; then
    return 1
  fi
  local mode
  mode="$(nmcli -t -f 802-11-wireless.mode con show "$conn" 2>/dev/null | cut -d: -f2)"
  if [[ "$mode" == "ap" ]]; then
    return 1
  fi
  return 0
}

cleanup() {
  if [[ -n "${PORTAL_PID:-}" ]]; then
    kill "$PORTAL_PID" >/dev/null 2>&1 || true
    wait "$PORTAL_PID" >/dev/null 2>&1 || true
  fi

  if [[ -n "${HOTSPOT_CONN:-}" ]]; then
    if nmcli -t -f NAME,TYPE con show --active 2>/dev/null | grep -q "^${HOTSPOT_CONN}:wifi"; then
      nmcli con down "$HOTSPOT_CONN" >/dev/null 2>&1 || true
    fi
  fi
}

trap cleanup EXIT

if ! have_nmcli; then
  log "nmcli not found; skipping wifi onboarding"
  exit 0
fi

nmcli radio wifi on >/dev/null 2>&1 || true

if wifi_connected; then
  log "Wi-Fi already connected; skipping onboarding"
  exit 0
fi

log "Starting hotspot '$HOTSPOT_SSID' on $HOTSPOT_IFACE"
if [[ -n "$HOTSPOT_PASS" && ${#HOTSPOT_PASS} -ge 8 ]]; then
  nmcli dev wifi hotspot ifname "$HOTSPOT_IFACE" ssid "$HOTSPOT_SSID" password "$HOTSPOT_PASS" >/dev/null
else
  nmcli dev wifi hotspot ifname "$HOTSPOT_IFACE" ssid "$HOTSPOT_SSID" >/dev/null
fi

HOTSPOT_CONN="$(nmcli -t -f NAME,TYPE con show --active | awk -F: '$2=="wifi" {print $1; exit}')"

log "Launching captive portal on port $PORTAL_PORT"
python3 "$SCRIPT_DIR/wifi_portal.py" --port "$PORTAL_PORT" --interface "$HOTSPOT_IFACE" --ssid "$HOTSPOT_SSID" &
PORTAL_PID=$!

START_TS=$(date +%s)
while true; do
  if wifi_connected; then
    log "Wi-Fi connected; shutting down hotspot"
    break
  fi

  NOW=$(date +%s)
  if (( NOW - START_TS >= TIMEOUT_S )); then
    log "Timeout reached (${TIMEOUT_S}s); stopping onboarding"
    break
  fi

  sleep 2
done

exit 0
