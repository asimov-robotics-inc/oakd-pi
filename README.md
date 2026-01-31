# OAK-D Egocentric Capture

Headless data capture system for robotics training. Raspberry Pi 5 + OAK-D Pro records synchronized RGB, stereo left/right, and IMU streams to MCAP format. Depth is intended to be computed offline from the stereo pair. Starts recording on boot, no screen or keyboard needed. If the camera isn't available at boot, the app keeps retrying until it is.

## What it captures

| Stream | Details |
|--------|---------|
| RGB | 480p @ 30fps, H.265 encoded on-camera (6 Mbps) |
| Stereo Left | 480p @ 30fps, H.265 encoded on-camera (6 Mbps) |
| Stereo Right | 480p @ 30fps, H.265 encoded on-camera (6 Mbps) |
| IMU | 200Hz accelerometer + gyroscope |
| IR | Dot projector at 50% for improved depth |

Streams are recorded independently and aligned offline using device timestamps or sequence numbers. Timestamps come from the device clock, not the Pi.

## Hardware

- Raspberry Pi 5 (Raspberry Pi OS Bookworm, Python 3.11)
- OAK-D Pro (USB-C, plugged into a **blue USB 3.0 port**)
- USB-C data cable
- Battery pack or wall power

## Deploying to Pis

There is one recommended way to get a Pi running: manual setup.

If you're setting up just one Pi with a monitor and keyboard attached:

```bash
# Clone the repo
git clone <repo-url> ~/oakd-pi
cd ~/oakd-pi

# Install system deps, uv, and Python packages (needs internet)
./setup.sh

# Start the systemd service
./run.sh
```

See [docs/pi_setup.md](docs/pi_setup.md) for the full walkthrough.

## Connectivity

### Ethernet (simplest)

Plug an Ethernet cable between your Mac/PC and the Pi (direct or via a switch). Raspberry Pi OS has mDNS enabled by default, so `ssh pi@raspberrypi.local` works out of the box with no Wi-Fi setup.

### Wi-Fi

Connect from a terminal on the Pi:

```bash
sudo nmcli device wifi connect "YOUR_SSID" password "YOUR_PASSWORD"
```

Or pre-configure Wi-Fi during SD card flashing with Raspberry Pi Imager.

### USB Ethernet gadget (no network hardware needed)

On Pi 4/5, you can create a virtual Ethernet link over the USB-C port. This lets you SSH into the Pi with just a USB-C cable — no Wi-Fi, no Ethernet, no router.

1. Add to `/boot/firmware/config.txt`:
   ```
   dtoverlay=dwc2
   ```

2. Add `modules-load=dwc2,g_ether` to the end of the kernel command line in `/boot/firmware/cmdline.txt` (same line, space-separated).

3. Reboot the Pi, then connect a USB-C cable from the Pi's USB-C port to your computer.

4. The Pi appears as a USB Ethernet device. SSH in:
   ```bash
   ssh pi@raspberrypi.local
   ```

Note: On Pi 4, the USB-C port is shared with power, so you'll need to power the Pi separately (e.g., via GPIO header) or use a USB-C cable that supports both data and power delivery.

## Managing the service

```bash
# Check status
ssh pi@host sudo systemctl status oakd-capture

# View live logs
ssh pi@host journalctl -u oakd-capture -f

# Restart
ssh pi@host sudo systemctl restart oakd-capture

# Stop and disable
ssh pi@host "sudo systemctl stop oakd-capture && sudo systemctl disable oakd-capture"
```

Or if you're on the Pi directly, use the helper scripts:

```bash
./run.sh    # enable + start
./stop.sh   # stop + disable
```

## Recordings

Saved to `~/recordings/YYYYMMDD_HHMMSS/` on the Pi (timestamps are UTC). The system
rotates to a new recording every 10 minutes for reliability.

```
~/recordings/
└── 20260130_143052/
    ├── recording_20260130_143052.mcap    # RGB + stereo L/R + IMU
    ├── calibration_20260130_143052.json  # camera intrinsics/extrinsics
    └── metadata_20260130_143052.json     # recording config + device info
    └── sync_index_20260130_143052.csv    # stream,seq,timestamp_ns for offline sync
```

MCAP payloads are raw binary — H.265 video frames (RGB + left + right) and 48-byte packed IMU structs (6 little-endian doubles: ax, ay, az, gx, gy, gz). The recording is fsynced to disk every 5 seconds to limit data loss on hard power cuts.

## Offline processing (sync + rectification + depth)

Recordings are intentionally raw. The expected offline steps for robotics labs are:

1) **Demux and decode**
   - Decode H.265 frames for `rgb`, `left`, and `right` topics.
2) **Stream alignment (offline)**
   - Use `sync_index_*.csv` for **sequence number** alignment (preferred).
   - If needed, align by **device timestamp** directly from MCAP log_time.
   - RGB/left/right are captured at the same FPS and share the device clock.
3) **Rectification**
   - Use `calibration_*.json` to compute rectification transforms for left/right.
   - Rectify the stereo pair before any disparity/depth estimation.
4) **Depth / disparity (optional)**
   - Run your preferred stereo matcher or learned depth model on rectified L/R.
5) **IMU alignment**
   - IMU samples are timestamped with the same device clock.
   - Align IMU to camera frames by nearest timestamp if needed.

### Copying recordings off the Pi

```bash
# Single session
scp -r pi@host:~/recordings/20260130_143052 ~/Downloads/

# All recordings
rsync -az pi@host:~/recordings/ ~/local-recordings/
```

## Project structure

```
oakd-pi/
├── pyproject.toml              # Python project config
├── .python-version             # Python version pin (3.11)
├── setup.sh                    # Manual single-Pi setup
├── run.sh / stop.sh            # systemd service helpers
├── src/oakd_capture/
│   ├── __init__.py
│   ├── __main__.py             # Entry point
│   └── main.py                 # Pipeline, recording, state machine
├── systemd/
│   └── oakd-capture.service    # systemd unit file
└── docs/
    ├── pi_setup.md             # Manual setup guide
    ├── status.md               # Milestone tracking
    └── changelog.md            # Version history
```

## Documentation

- [Pi Setup Guide](docs/pi_setup.md) — manual single-Pi setup with monitor/keyboard
- [Project Spec](PROJECT_SPEC.md) — full specification
- [Changelog](docs/changelog.md) — version history
- [Status](docs/status.md) — milestone tracking
