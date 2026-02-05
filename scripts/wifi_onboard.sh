#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

TIMEOUT_S="${WIFI_ONBOARD_TIMEOUT_S:-300}"
HOTSPOT_SSID="${WIFI_HOTSPOT_SSID:-recording-device-setup}"
HOTSPOT_PASS="${WIFI_HOTSPOT_PASS:-}"
HOTSPOT_IFACE="${WIFI_HOTSPOT_IFACE:-wlan0}"
PORTAL_PORT="${WIFI_PORTAL_PORT:-80}"
HOTSPOT_IP="${WIFI_HOTSPOT_IP:-192.168.4.1/24}"
HOTSPOT_IP_ADDR="${HOTSPOT_IP%/*}"
CREDS_PATH="${WIFI_CREDS_PATH:-/tmp/oakd-wifi-creds.json}"
HOSTAPD_CONF="/tmp/oakd-hostapd.conf"
DNSMASQ_CONF="/tmp/oakd-dnsmasq.conf"
HOSTAPD_PID="/tmp/oakd-hostapd.pid"
DNSMASQ_PID="/tmp/oakd-dnsmasq.pid"
PORTAL_PID=""
DNSMASQ_SYSTEM_STOPPED=""

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

remove_existing_hotspot() {
  set +e
  nmcli -t -f NAME,TYPE con show 2>/dev/null | \
    awk -F: '$2=="802-11-wireless" {print $1}' | \
    while read -r name; do
      if [[ -z "$name" ]]; then
        continue
      fi
      ssid="$(nmcli -g 802-11-wireless.ssid con show "$name" 2>/dev/null | head -n1)"
      if [[ "$ssid" == "$HOTSPOT_SSID" ]]; then
        nmcli con delete "$name" >/dev/null 2>&1 || true
      fi
    done
  set -e
}

cleanup() {
  if [[ -n "${PORTAL_PID:-}" ]]; then
    kill "$PORTAL_PID" >/dev/null 2>&1 || true
    wait "$PORTAL_PID" >/dev/null 2>&1 || true
  fi

  if [[ -f "$HOSTAPD_PID" ]]; then
    kill "$(cat "$HOSTAPD_PID")" >/dev/null 2>&1 || true
  fi
  if [[ -f "$DNSMASQ_PID" ]]; then
    kill "$(cat "$DNSMASQ_PID")" >/dev/null 2>&1 || true
  fi
  rm -f "$HOSTAPD_PID" "$DNSMASQ_PID" "$HOSTAPD_CONF" "$DNSMASQ_CONF" "$CREDS_PATH"

  if [[ -n "$DNSMASQ_SYSTEM_STOPPED" ]]; then
    systemctl start dnsmasq >/dev/null 2>&1 || true
  fi

  ip addr flush dev "$HOTSPOT_IFACE" >/dev/null 2>&1 || true
  ip link set "$HOTSPOT_IFACE" down >/dev/null 2>&1 || true
  ip link set "$HOTSPOT_IFACE" up >/dev/null 2>&1 || true

  if have_nmcli; then
    nmcli dev set "$HOTSPOT_IFACE" managed yes >/dev/null 2>&1 || true
  fi
}

trap cleanup EXIT

if ! command -v hostapd >/dev/null 2>&1 || ! command -v dnsmasq >/dev/null 2>&1; then
  log "hostapd or dnsmasq not found; skipping wifi onboarding"
  exit 0
fi

if have_nmcli; then
  nmcli radio wifi on >/dev/null 2>&1 || true
  nmcli dev set "$HOTSPOT_IFACE" managed no >/dev/null 2>&1 || true
fi

if wifi_connected; then
  log "Wi-Fi already connected; skipping onboarding"
  exit 0
fi

remove_existing_hotspot

start_hotspot() {
  log "Starting hotspot '$HOTSPOT_SSID' on $HOTSPOT_IFACE"
  ip link set "$HOTSPOT_IFACE" down >/dev/null 2>&1 || true
  ip addr flush dev "$HOTSPOT_IFACE" >/dev/null 2>&1 || true
  ip addr add "$HOTSPOT_IP" dev "$HOTSPOT_IFACE" >/dev/null 2>&1 || true
  ip link set "$HOTSPOT_IFACE" up >/dev/null 2>&1 || true

  if systemctl is-active dnsmasq >/dev/null 2>&1; then
    systemctl stop dnsmasq >/dev/null 2>&1 || true
    DNSMASQ_SYSTEM_STOPPED=1
  fi

  cat > "$HOSTAPD_CONF" <<EOF
interface=$HOTSPOT_IFACE
driver=nl80211
ssid=$HOTSPOT_SSID
hw_mode=g
channel=6
auth_algs=1
ignore_broadcast_ssid=0
wmm_enabled=0
EOF

  if [[ -n "$HOTSPOT_PASS" && ${#HOTSPOT_PASS} -ge 8 ]]; then
    cat >> "$HOSTAPD_CONF" <<EOF
wpa=2
wpa_passphrase=$HOTSPOT_PASS
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
EOF
  fi

  cat > "$DNSMASQ_CONF" <<EOF
interface=$HOTSPOT_IFACE
bind-interfaces
dhcp-range=192.168.4.2,192.168.4.50,255.255.255.0,24h
dhcp-option=option:router,${HOTSPOT_IP_ADDR}
dhcp-option=option:dns-server,${HOTSPOT_IP_ADDR}
address=/#/${HOTSPOT_IP_ADDR}
no-resolv
no-hosts
EOF

  hostapd -B -P "$HOSTAPD_PID" "$HOSTAPD_CONF" >/dev/null 2>&1
  dnsmasq --conf-file="$DNSMASQ_CONF" --pid-file="$DNSMASQ_PID" >/dev/null 2>&1
}

start_hotspot

log "Launching captive portal on port $PORTAL_PORT"
python3 "$SCRIPT_DIR/wifi_portal.py" \
  --port "$PORTAL_PORT" \
  --interface "$HOTSPOT_IFACE" \
  --ssid "$HOTSPOT_SSID" \
  --dns-ip "$HOTSPOT_IP_ADDR" \
  --no-dns \
  --out "$CREDS_PATH" &
PORTAL_PID=$!

START_TS=$(date +%s)
while true; do
  if [[ -f "$CREDS_PATH" ]]; then
    ssid="$(python3 - <<PY
import json
import sys
with open("$CREDS_PATH", "r", encoding="utf-8") as f:
    data = json.load(f)
print(data.get("ssid", ""))
PY
)"
    password="$(python3 - <<PY
import json
import sys
with open("$CREDS_PATH", "r", encoding="utf-8") as f:
    data = json.load(f)
print(data.get("password", ""))
PY
)"

    log "Received credentials for '$ssid'"

    # Stop hotspot and switch back to managed mode
    cleanup

    if have_nmcli; then
      if [[ -n "$password" ]]; then
        if nmcli dev wifi connect "$ssid" password "$password" >/dev/null 2>&1; then
          exit 0
        fi
      else
        if nmcli dev wifi connect "$ssid" >/dev/null 2>&1; then
          exit 0
        fi
      fi
    fi

    log "Failed to connect; restarting hotspot"
    if have_nmcli; then
      nmcli dev set "$HOTSPOT_IFACE" managed no >/dev/null 2>&1 || true
    fi
    start_hotspot
    python3 "$SCRIPT_DIR/wifi_portal.py" --port "$PORTAL_PORT" --interface "$HOTSPOT_IFACE" --ssid "$HOTSPOT_SSID" --dns-ip "$HOTSPOT_IP_ADDR" --no-dns --out "$CREDS_PATH" &
    PORTAL_PID=$!
  fi

  NOW=$(date +%s)
  if (( NOW - START_TS >= TIMEOUT_S )); then
    log "Timeout reached (${TIMEOUT_S}s); stopping onboarding"
    break
  fi

  sleep 2
done

exit 0
