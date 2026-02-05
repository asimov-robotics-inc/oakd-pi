#!/usr/bin/env python3
import argparse
import html
import socket
import struct
import subprocess
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer


def scan_networks() -> list[dict]:
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "SSID,SECURITY,SIGNAL", "dev", "wifi", "list"],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return []

    networks = {}
    for line in result.stdout.splitlines():
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
        # Keep strongest signal for duplicates
        if ssid not in networks or networks[ssid]["signal"] < signal_val:
            networks[ssid] = {
                "ssid": ssid,
                "security": security or "open",
                "signal": signal_val,
            }

    return sorted(networks.values(), key=lambda x: x["signal"], reverse=True)


class WifiPortalHandler(BaseHTTPRequestHandler):
    def _send(self, body: str, status: int = 200) -> None:
        body_bytes = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def do_GET(self) -> None:
        captive_paths = {
            "/hotspot-detect.html",  # Apple
            "/generate_204",         # Android
            "/gen_204",
            "/ncsi.txt",             # Windows
            "/connecttest.txt",      # Windows
        }
        if self.path in captive_paths:
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
            return

        if self.path not in ("/", "/index.html"):
            self._send("Not Found", status=404)
            return

        networks = scan_networks()
        options = [
            f"<option value=\"{html.escape(n['ssid'])}\">"
            f"{html.escape(n['ssid'])} ({n['signal']}%, {html.escape(n['security'])})"
            "</option>"
            for n in networks
        ]
        options_html = "\n".join(options) if options else "<option>(no networks found)</option>"

        page = f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>OAK-D Wi-Fi Setup</title>
    <style>
      body {{ font-family: Arial, sans-serif; margin: 24px; }}
      .card {{ max-width: 420px; margin: 0 auto; }}
      label {{ display: block; margin-top: 12px; font-weight: bold; }}
      input, select, button {{ width: 100%; padding: 10px; margin-top: 6px; }}
      button {{ margin-top: 16px; }}
      .note {{ font-size: 12px; color: #555; margin-top: 8px; }}
    </style>
  </head>
  <body>
    <div class="card">
      <h2>Connect OAK-D Pi to Wi-Fi</h2>
      <form method="POST" action="/connect">
        <label for="ssid">Select network</label>
        <select name="ssid" id="ssid">
          {options_html}
        </select>

        <label for="ssid_manual">Or enter SSID</label>
        <input type="text" id="ssid_manual" name="ssid_manual" placeholder="Hidden network SSID" />

        <label for="password">Password</label>
        <input type="password" id="password" name="password" placeholder="Wi-Fi password" />

        <button type="submit">Connect</button>
      </form>
      <p class="note">If this page doesn't refresh, try reconnecting to the hotspot and reload.</p>
    </div>
  </body>
</html>
"""
        self._send(page)

    def do_POST(self) -> None:
        if self.path != "/connect":
            self._send("Not Found", status=404)
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        params = urllib.parse.parse_qs(body)
        ssid = (params.get("ssid_manual") or params.get("ssid") or [""])[0].strip()
        password = (params.get("password") or [""])[0]

        if not ssid:
            self._send("<h3>SSID required. Go back and try again.</h3>")
            return

        cmd = ["nmcli", "dev", "wifi", "connect", ssid]
        if password:
            cmd += ["password", password]
        if self.server.interface:
            cmd += ["ifname", self.server.interface]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            self._send("<h3>Connected. You can close this page.</h3>")
        else:
            err = html.escape(result.stderr.strip() or "Unknown error")
            self._send(f"<h3>Failed to connect:</h3><pre>{err}</pre>")


class DnsHijackServer(threading.Thread):
    def __init__(self, ip: str, port: int = 53):
        super().__init__(daemon=True)
        self.ip = ip
        self.port = port
        self.sock = None

    def run(self) -> None:
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind(("0.0.0.0", self.port))
        except Exception as exc:
            print(f"DNS server failed to start: {exc}")
            return

        while True:
            try:
                data, addr = self.sock.recvfrom(512)
                if len(data) < 12:
                    continue
                tid = data[:2]
                flags = b"\x81\x80"
                qdcount = data[4:6]
                ancount = qdcount
                nscount = b"\x00\x00"
                arcount = b"\x00\x00"

                # Parse question section
                idx = 12
                while idx < len(data) and data[idx] != 0:
                    idx += 1 + data[idx]
                idx += 1  # null terminator
                idx += 4  # QTYPE + QCLASS
                if idx > len(data):
                    continue
                question = data[12:idx]

                # Answer: pointer to name (0xC00C), type A, class IN, TTL, RDLENGTH, RDATA
                answer = b"\xc0\x0c" + b"\x00\x01" + b"\x00\x01" + b"\x00\x00\x00\x3c" + b"\x00\x04"
                answer += socket.inet_aton(self.ip)

                resp = tid + flags + qdcount + ancount + nscount + arcount + question + answer
                self.sock.sendto(resp, addr)
            except Exception:
                continue


class WifiPortalServer(HTTPServer):
    def __init__(self, server_address, handler_class, interface: str):
        super().__init__(server_address, handler_class)
        self.interface = interface


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=80)
    parser.add_argument("--interface", default="wlan0")
    parser.add_argument("--ssid", default="oakd-setup")
    parser.add_argument("--dns-ip", default="192.168.4.1")
    args = parser.parse_args()

    DnsHijackServer(args.dns_ip).start()

    server = WifiPortalServer((args.host, args.port), WifiPortalHandler, args.interface)
    print(f"Wi-Fi portal running on {args.host}:{args.port} (hotspot: {args.ssid})")
    server.serve_forever()


if __name__ == "__main__":
    main()
