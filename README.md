# OAK-D Egocentric Capture

Headless data capture system for robotics training. Raspberry Pi 5 + OAK-D Pro records synchronized RGB, stereo left/right, and IMU streams to MCAP format. Depth is intended to be computed offline from the stereo pair. Starts recording on boot, no screen or keyboard needed. If the camera isn't available at boot, the app keeps retrying until it is.

## What it captures

| Stream | Details |
|--------|---------|
| RGB | 720p @ 30fps, H.265 encoded on-camera (10 Mbps) |
| Stereo Left | 720p @ 30fps, H.265 encoded on-camera (10 Mbps) |
| Stereo Right | 720p @ 30fps, H.265 encoded on-camera (10 Mbps) |
| IMU | 200Hz accelerometer + gyroscope |
| IR | Dot projector at 50% for improved depth |

All streams are software-synchronized via DepthAI Sync node (<10ms threshold). Timestamps come from the device clock, not the Pi.

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
```

MCAP payloads are raw binary — H.265 video frames (RGB + left + right) and 48-byte packed IMU structs (6 little-endian doubles: ax, ay, az, gx, gy, gz). The recording is fsynced to disk every 5 seconds to limit data loss on hard power cuts.

### Copying recordings off the Pi

```bash
# Single session
scp -r pi@host:~/recordings/20260130_143052 ~/Downloads/

# All recordings
rsync -az pi@host:~/recordings/ ~/local-recordings/
```

### Viewing recordings

```bash
# Install viewer dependencies (on any machine with a display)
uv sync --extra viewer

# Play back a recording
uv run python tools/viewer.py ~/local-recordings/20260130_143052/recording_20260130_143052.mcap
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
├── tools/
│   └── viewer.py               # MCAP playback viewer
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
