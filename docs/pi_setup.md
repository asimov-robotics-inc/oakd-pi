# Raspberry Pi 5 Setup Guide

Manual setup for a single Pi with a monitor and keyboard attached. This installs
all build tools (git, uv, python3-dev) and compiles dependencies from source.

This guide covers the manual setup flow for a Pi with a monitor and keyboard.

## Prerequisites

- Raspberry Pi 5 with Raspberry Pi OS Bookworm booted and working
- Monitor + keyboard + mouse connected to the Pi
- Internet connection (Wi-Fi or Ethernet)
- This repo already cloned to `~/oakd-pi`
- OAK-D Pro + USB-C data cable

### OAK-D Pro Connection

Plug the OAK-D Pro's USB-C cable into one of the Pi 5's **blue USB 3.0 ports**
(not the black USB 2.0 ports). USB 3.0 is needed for camera bandwidth.

## 1. Connect to WiFi (if not already connected)

Open a terminal on the Pi and connect to your network:

```bash
sudo nmcli device wifi connect "YOUR_SSID" password "YOUR_PASSWORD"
```

Verify the connection:

```bash
ip addr show wlan0
```

You should see an IP address assigned. WiFi is needed for installing packages.

## 2. System Setup

```bash
cd ~/oakd-pi
./setup.sh
```

This installs system dependencies, OAK-D udev rules, uv, and project packages.

## 2.1 Set a Unique Hostname (always do this)

If you are setting up multiple Pis, **always** set a unique hostname so `.local`
discovery is stable and you don’t fight SSH host key mismatches.

```bash
sudo hostnamectl set-hostname pi-01
```

Reconnect using the new hostname:

```bash
ssh pi@pi-01.local
```

## 3. Verify OAK-D is Detected

With the OAK-D plugged into a blue USB 3.0 port:

```bash
uv run python -c "import depthai; print(depthai.Device.getAllAvailableDevices())"
```

You should see at least one device listed.

## 4. Run on Boot

To enable auto-recording on startup:

```bash
./run.sh
```

To stop and disable:

```bash
./stop.sh
```

Check status and logs:

```bash
sudo systemctl status oakd-capture
journalctl -u oakd-capture -f
```

## 4.2 Wi-Fi Onboarding (optional)

On boot, the Pi can open a temporary Wi-Fi hotspot for up to 5 minutes so you can enter credentials from your phone.

- Connect to the hotspot SSID `recording-device-setup` (open, no password).
- A captive portal should open automatically.
- If it doesn't, open `http://192.168.4.1`.

Once connected, credentials are saved and the hotspot stops.
This flow assumes NetworkManager (default on Raspberry Pi OS Bookworm).

## 4.3 S3 Uploads (optional)

If Wi-Fi is connected and S3 credentials are configured, completed recording segments are uploaded to S3 and deleted locally to free space. Uploads only run when a `.done` marker exists for a segment.

Create `/etc/oakd/s3.env`:

```bash
S3_BUCKET=your-bucket
S3_PREFIX=oakd-recordings
S3_REGION=us-east-1
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
```

Template: `docs/s3.env.example`.

## 4.4 Updating the Pi

If you pull new code changes on the Pi, stop the service first, then update, then restart.

```bash
cd ~/oakd-pi
./stop.sh
git pull
./run.sh
```

If you only changed Python dependencies, re-sync them before restarting:

```bash
uv sync
```

## 5. Retrieve Recordings

Recordings are saved to `~/recordings/` on the Pi. Each session gets its own
timestamped folder, and the system rotates to a new recording every 10 minutes.

```bash
# list recording sessions
ls -la ~/recordings/
```

Each folder contains:
- `recording_YYYYMMDD_HHMMSS.mcap` - sensor data (RGB + left/right mono + IMU @ 200Hz)
- `calibration_YYYYMMDD_HHMMSS.json` - camera intrinsics/extrinsics
- `metadata_YYYYMMDD_HHMMSS.json` - recording config + device info
- `.done` - marker file created when a segment is fully closed (used for S3 upload)

### Copying recordings to another machine

To transfer recordings off the Pi, you can use a USB drive or SSH from another
computer on the same network:

```bash
# from your laptop
scp -r pi@pi.local:~/recordings/YYYYMMDD_HHMMSS ~/Downloads/
```

### Setting up SSH (optional)

If you want to access the Pi remotely after initial setup:

```bash
# on the Pi - enable SSH
sudo systemctl enable ssh
sudo systemctl start ssh
```

Then from another machine on the same network:

```bash
ssh pi@pi.local
```

## 6. Headless Validation (exact test flow)

Use this when you have the Pi on the network and want to run a short test recording, then verify the actual FPS, resolutions, and IMU Hz from the MCAP. **Always do this after setup.**

### 6.1 Connect and resolve host key issues

```bash
# First connect (accept the host key prompt)
ssh pi@raspberrypi.local
```

If you see a host key mismatch error (common when re-flashing multiple Pis), remove the old key and retry:

```bash
ssh-keygen -R raspberrypi.local
ssh pi@raspberrypi.local
```

If you have multiple Pis, set a unique hostname on each one so `*.local` works reliably:

```bash
sudo hostnamectl set-hostname pi-01
```

Then reconnect with:

```bash
ssh pi@pi-01.local
```

### 6.2 Run a short test recording

Stop the service, run a 20s capture, then restart the service:

```bash
sudo systemctl stop oakd-capture
cd ~/oakd-pi
timeout 20s ./.venv/bin/python -m oakd_capture
sudo systemctl start oakd-capture
```

Find the latest recording folder:

```bash
ls -t ~/recordings | head -n1
```

### 6.3 Verify FPS, IMU Hz, and resolutions from the MCAP

On the Pi, run this in the recording folder you just created (replace the timestamp):

```bash
REC_DIR=~/recordings/YYYYMMDD_HHMMSS
REC="$REC_DIR/recording_YYYYMMDD_HHMMSS.mcap"

./.venv/bin/python - <<PY
from mcap.stream_reader import StreamReader
from mcap.records import Channel, Message
from pathlib import Path

mcap_path = Path("$REC")
channels = {}
stats = {}
frames = {"/oak/rgb": [], "/oak/left": [], "/oak/right": []}

with mcap_path.open("rb") as f:
    reader = StreamReader(f, record_size_limit=None)
    for record in reader.records:
        if isinstance(record, Channel):
            channels[record.id] = record.topic
        elif isinstance(record, Message):
            topic = channels.get(record.channel_id, f"ch{record.channel_id}")
            st = stats.setdefault(topic, {"count": 0, "first": None, "last": None})
            st["count"] += 1
            ts = record.log_time
            if st["first"] is None:
                st["first"] = ts
            st["last"] = ts
            if topic in frames and len(frames[topic]) < 3:
                frames[topic].append(record.data)

out_dir = Path("$REC_DIR")
(out_dir / "tmp_rgb.h265").write_bytes(b"".join(frames["/oak/rgb"]))
(out_dir / "tmp_left.mjpg").write_bytes(b"".join(frames["/oak/left"]))
(out_dir / "tmp_right.mjpg").write_bytes(b"".join(frames["/oak/right"]))

for topic in sorted(stats.keys()):
    st = stats[topic]
    if st["first"] is None or st["last"] is None or st["last"] == st["first"]:
        rate = 0.0
        duration = 0.0
    else:
        duration = (st["last"] - st["first"]) / 1e9
        rate = st["count"] / duration if duration > 0 else 0.0
    count = st["count"]
    print(f"{topic}: count={count} duration_s={duration:.3f} rate={rate:.2f}")
PY

# Probe resolution from the extracted frame bytes
ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 -f hevc "$REC_DIR/tmp_rgb.h265"
ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 -f mjpeg "$REC_DIR/tmp_left.mjpg"
ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 -f mjpeg "$REC_DIR/tmp_right.mjpg"

# Cleanup temp files
rm -f "$REC_DIR/tmp_rgb.h265" "$REC_DIR/tmp_left.mjpg" "$REC_DIR/tmp_right.mjpg"
```

Expected output should be very close to:

```text
/oak/rgb:   ~30 fps
/oak/left:  ~30 fps
/oak/right: ~30 fps
/oak/imu:   ~200 Hz
RGB: 1280x720
Mono: 1280x800
```

### 6.4 Copy the recording to your laptop (optional)

From your laptop:

```bash
rsync -az pi@pi-01.local:~/recordings/YYYYMMDD_HHMMSS/ ./test-recording/pi-01_YYYYMMDD_HHMMSS/
```

## Troubleshooting

### Can't connect to WiFi

- Double-check SSID and password (they're case-sensitive)
- Run `nmcli device wifi list` to see available networks
- Make sure the Pi's WiFi antenna isn't obstructed

### Camera bandwidth errors (X_LINK_ERROR)

Use the blue USB 3.0 ports, not USB 2.0. The current config uses:
- RGB: 1280x720 (H.265)
- Mono left/right: 1280x800 (MJPEG)

If errors persist, try a powered USB hub or reduce FPS/resolution.

### Camera not ready at boot

The app keeps retrying device initialization every few seconds. If the camera is
unplugged or slow to enumerate, it should begin recording as soon as it appears.
Check logs with:

```bash
journalctl -u oakd-capture -f
```
