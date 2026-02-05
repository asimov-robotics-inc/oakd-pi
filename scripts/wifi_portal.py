#!/usr/bin/env python3
import argparse
import html
import json
import subprocess
import socket
import struct
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer


def scan_networks(cache_path: str | None = None) -> list[dict]:
    if cache_path:
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and data:
                return data
        except Exception:
            pass

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
        if self.path == "/status":
            status = {"state": "idle"}
            if self.server.status_path:
                try:
                    with open(self.server.status_path, "r", encoding="utf-8") as f:
                        status = json.load(f)
                except Exception:
                    status = {"state": "idle"}
            body = json.dumps(status).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
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

        networks = scan_networks(self.server.scan_cache)
        options = [
            f"<option value=\"{html.escape(n['ssid'])}\">{html.escape(n['ssid'])}</option>"
            for n in networks
        ]
        options_html = "\n".join(options) if options else "<option value=\"\">(no networks found)</option>"
        has_networks = "true" if options else "false"

        page = f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Wi-Fi Setup</title>
    <style>
      body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
        margin: 0;
        background: linear-gradient(180deg, #f7f8fb, #eef1f6);
        color: #1f2937;
      }}
      .wrap {{
        min-height: 100vh;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 24px;
      }}
      .card {{
        width: 100%;
        max-width: 420px;
        background: #ffffff;
        border-radius: 16px;
        padding: 24px;
        box-shadow: 0 10px 30px rgba(31, 41, 55, 0.12);
      }}
      h2 {{
        margin: 0 0 8px 0;
        font-size: 20px;
      }}
      .subtitle {{
        margin: 0 0 20px 0;
        font-size: 13px;
        color: #6b7280;
      }}
      label {{
        display: block;
        margin-top: 12px;
        font-weight: 600;
        font-size: 13px;
      }}
      select, input {{
        width: 100%;
        padding: 12px;
        margin-top: 6px;
        border: 1px solid #e5e7eb;
        border-radius: 10px;
        font-size: 14px;
        background: #f9fafb;
        box-sizing: border-box;
        appearance: none;
        -webkit-appearance: none;
      }}
      select {{
        display: block;
      }}
      button {{
        width: 100%;
        padding: 12px;
        margin-top: 16px;
        border: 0;
        border-radius: 10px;
        font-size: 15px;
        font-weight: 600;
        color: #fff;
        background: #2563eb;
      }}
      button:disabled {{
        background: #94a3b8;
      }}
      .note {{
        font-size: 12px;
        color: #6b7280;
        margin-top: 8px;
      }}
      .refresh {{
        display: inline-block;
        margin-top: 6px;
        font-size: 12px;
        color: #2563eb;
        text-decoration: none;
      }}
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="card">
        <h2>Connect to Wi‑Fi</h2>
        <p class="subtitle">Choose a network and enter the password.</p>
        <form method="POST" action="/connect">
          <label for="ssid">Select network</label>
          <select name="ssid" id="ssid">
            {options_html}
          </select>

          <label for="password">Password</label>
          <input type="password" id="password" name="password" placeholder="Leave blank if open" />

          <button id="connect" type="submit">Connect</button>
        </form>
        <p class="note">If you don't see your network, wait a moment and refresh.</p>
        <a class="refresh" href="/">Refresh list</a>
      </div>
    </div>
    <script>
      const hasNetworks = {has_networks};
      const btn = document.getElementById('connect');
      const sel = document.getElementById('ssid');
      if (!hasNetworks) {{
        btn.disabled = true;
        sel.disabled = true;
      }}
    </script>
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
        ssid = (params.get("ssid") or [""])[0].strip()
        password = (params.get("password") or [""])[0]

        if not ssid:
            self._send("<h3>SSID required. Go back and try again.</h3>")
            return

        try:
            with open(self.server.creds_path, "w", encoding="utf-8") as f:
                json.dump({"ssid": ssid, "password": password}, f)
            if self.server.status_path:
                with open(self.server.status_path, "w", encoding="utf-8") as f:
                    json.dump({"state": "received", "message": "Credentials received"}, f)
            page = f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Connecting...</title>
    <style>
      body {{ font-family: Arial, sans-serif; margin: 24px; }}
      .card {{ max-width: 420px; margin: 0 auto; }}
      .status {{ margin-top: 12px; }}
      a {{ display: inline-block; margin-top: 12px; }}
    </style>
  </head>
  <body>
    <div class="card">
      <h2>Connecting to {html.escape(ssid)}</h2>
      <div class="status" id="status">Attempting to connect...</div>
      <a href="/" id="retry" style="display:none;">Try again</a>
      <p>If connection succeeds, this hotspot will disappear.</p>
    </div>
    <script>
      async function poll() {{
        try {{
          const res = await fetch('/status', {{cache: 'no-store'}});
          const data = await res.json();
          if (data.state === 'success') {{
            document.getElementById('status').textContent = data.message || 'Connected.';
          }} else if (data.state === 'failed') {{
            document.getElementById('status').textContent = data.message || 'Failed to connect.';
            document.getElementById('retry').style.display = 'inline-block';
          }}
        }} catch (e) {{}}
      }}
      setInterval(poll, 2000);
      poll();
    </script>
  </body>
</html>
"""
            self._send(page)
        except Exception as exc:
            err = html.escape(str(exc))
            self._send(f"<h3>Failed to save credentials:</h3><pre>{err}</pre>")


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
            print(f"DNS server failed to start: {exc}", flush=True)
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
    def __init__(
        self,
        server_address,
        handler_class,
        interface: str,
        creds_path: str,
        scan_cache: str | None,
        status_path: str | None,
    ):
        super().__init__(server_address, handler_class)
        self.interface = interface
        self.creds_path = creds_path
        self.scan_cache = scan_cache
        self.status_path = status_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=80)
    parser.add_argument("--interface", default="wlan0")
    parser.add_argument("--ssid", default="oakd-setup")
    parser.add_argument("--dns-ip", default="192.168.4.1")
    parser.add_argument("--no-dns", action="store_true")
    parser.add_argument("--out", default="/tmp/oakd-wifi-creds.json")
    parser.add_argument("--scan-cache", default=None)
    parser.add_argument("--status", default="/tmp/oakd-wifi-status.json")
    args = parser.parse_args()

    if not args.no_dns:
        DnsHijackServer(args.dns_ip).start()

    server = WifiPortalServer(
        (args.host, args.port),
        WifiPortalHandler,
        args.interface,
        args.out,
        args.scan_cache,
        args.status,
    )
    print(f"Wi-Fi portal running on {args.host}:{args.port} (hotspot: {args.ssid})")
    server.serve_forever()


if __name__ == "__main__":
    main()
