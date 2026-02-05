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
STATUS_PATH="${WIFI_STATUS_PATH:-/tmp/oakd-wifi-status.json}"
HOSTAPD_CONF="/tmp/oakd-hostapd.conf"
DNSMASQ_CONF="/tmp/oakd-dnsmasq.conf"
HOSTAPD_PID="/tmp/oakd-hostapd.pid"
DNSMASQ_PID="/tmp/oakd-dnsmasq.pid"
PORTAL_PID=""
DNSMASQ_SYSTEM_STOPPED=""
SCAN_CACHE="/tmp/oakd-wifi-scan.json"

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

write_scan_cache() {
  if ! have_nmcli; then
    return
  fi
  nmcli radio wifi on >/dev/null 2>&1 || true
  nmcli dev wifi rescan ifname "$HOTSPOT_IFACE" >/dev/null 2>&1 || true
  sleep 2
  nmcli -t -f SSID,SECURITY,SIGNAL dev wifi list ifname "$HOTSPOT_IFACE" > /tmp/oakd-wifi-scan.txt || true
  python3 - <<PY
import json
from pathlib import Path

raw = Path("/tmp/oakd-wifi-scan.txt").read_text(encoding="utf-8", errors="ignore")
networks = {}
for line in raw.splitlines():
    parts = line.split(":", 2)
    if len(parts) != 3:
        continue
    ssid, security, signal = parts
    ssid = ssid.strip()
    if not ssid:
        continue
    try:
        signal_val = int(signal)
    except ValueError:
        signal_val = 0
    if ssid not in networks or networks[ssid]["signal"] < signal_val:
        networks[ssid] = {
            "ssid": ssid,
            "security": security or "open",
            "signal": signal_val,
        }

out = sorted(networks.values(), key=lambda x: x["signal"], reverse=True)
Path("$SCAN_CACHE").write_text(json.dumps(out), encoding="utf-8")
PY
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
  rm -f "$HOSTAPD_PID" "$DNSMASQ_PID" "$HOSTAPD_CONF" "$DNSMASQ_CONF" "$CREDS_PATH" "$STATUS_PATH"

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

write_status() {
  local state="$1"
  local message="${2:-}"
  python3 - <<PY
import json
from pathlib import Path

payload = {"state": "$state"}
if "$message":
    payload["message"] = "$message"

Path("$STATUS_PATH").write_text(json.dumps(payload), encoding="utf-8")
PY
}

trap cleanup EXIT

if ! command -v hostapd >/dev/null 2>&1 || ! command -v dnsmasq >/dev/null 2>&1; then
  log "hostapd or dnsmasq not found; skipping wifi onboarding"
  exit 0
fi

if have_nmcli; then
  nmcli radio wifi on >/dev/null 2>&1 || true
  write_scan_cache
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

stop_hotspot() {
  if [[ -f "$HOSTAPD_PID" ]]; then
    kill "$(cat "$HOSTAPD_PID")" >/dev/null 2>&1 || true
  fi
  if [[ -f "$DNSMASQ_PID" ]]; then
    kill "$(cat "$DNSMASQ_PID")" >/dev/null 2>&1 || true
  fi
  rm -f "$HOSTAPD_PID" "$DNSMASQ_PID"
  ip addr flush dev "$HOTSPOT_IFACE" >/dev/null 2>&1 || true
  if have_nmcli; then
    nmcli dev set "$HOTSPOT_IFACE" managed yes >/dev/null 2>&1 || true
  fi
}

start_hotspot

log "Launching captive portal on port $PORTAL_PORT"
python3 "$SCRIPT_DIR/wifi_portal.py" \
  --port "$PORTAL_PORT" \
  --interface "$HOTSPOT_IFACE" \
  --ssid "$HOTSPOT_SSID" \
  --dns-ip "$HOTSPOT_IP_ADDR" \
  --no-dns \
  --out "$CREDS_PATH" \
  --status "$STATUS_PATH" \
  --scan-cache "$SCAN_CACHE" &
PORTAL_PID=$!
write_status "idle"

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

    rm -f "$CREDS_PATH" || true

    log "Received credentials for '$ssid'"
    write_status "connecting" "Attempting to connect..."
    err=""

    # Stop hotspot and switch back to managed mode
    stop_hotspot

    if have_nmcli; then
      if [[ -n "$password" ]]; then
        err="$(nmcli dev wifi connect "$ssid" password "$password" 2>&1)" && ok=1 || ok=0
        if [[ "$ok" -eq 1 ]]; then
          write_status "success" "Connected to $ssid"
          exit 0
        fi
      else
        err="$(nmcli dev wifi connect "$ssid" 2>&1)" && ok=1 || ok=0
        if [[ "$ok" -eq 1 ]]; then
          write_status "success" "Connected to $ssid"
          exit 0
        fi
      fi
    fi

    if [[ -n "$err" ]]; then
      write_status "failed" "$err"
    else
      write_status "failed" "Failed to connect. Check password or try another network."
    fi
    log "Failed to connect; restarting hotspot"
    if have_nmcli; then
      nmcli dev set "$HOTSPOT_IFACE" managed no >/dev/null 2>&1 || true
    fi
    start_hotspot
    # portal already running; leave it up
  fi

  NOW=$(date +%s)
  if (( NOW - START_TS >= TIMEOUT_S )); then
    log "Timeout reached (${TIMEOUT_S}s); stopping onboarding"
    break
  fi

  sleep 2
done

exit 0
