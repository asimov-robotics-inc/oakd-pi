# OAK-D Egocentric Capture

Headless data capture system for robotics training. Raspberry Pi 5 + OAK-D Pro records synchronized RGB, depth, and IMU streams to MCAP format. Starts recording on boot, no screen or keyboard needed.

## What it captures

| Stream | Details |
|--------|---------|
| RGB | 720p @ 30fps, H.265 encoded on-camera (10 Mbps) |
| Depth | StereoDepth computed on-device, aligned to RGB |
| IMU | 200Hz accelerometer + gyroscope |
| IR | Dot projector at 50% for improved depth |

All streams are software-synchronized via DepthAI Sync node (<10ms threshold). Timestamps come from the device clock, not the Pi.

## Hardware

- Raspberry Pi 5 (Raspberry Pi OS Bookworm, Python 3.11)
- OAK-D Pro (USB-C, plugged into a **blue USB 3.0 port**)
- USB-C data cable
- Battery pack or wall power

## Deploying to Pis

There are two ways to get a Pi running. The **bundle method** is recommended for deploying multiple Pis — it's faster, works offline (mostly), and doesn't require git or uv on the target.

### Option A: Bundle deploy (recommended)

This separates "build once" from "deploy many." You create a portable tarball on one configured Pi, then push it to any number of fresh Pis from your dev machine.

#### 1. Build the bundle (on a configured Pi)

If you already have one Pi set up the old way (via `setup.sh`), create the bundle:

```bash
cd ~/oakd-pi
./bundle.sh
# produces oakd-capture-bundle.tar.gz (~60-80MB)
```

#### 2. Copy the bundle to your dev machine

```bash
scp pi@reference-pi.local:~/oakd-pi/oakd-capture-bundle.tar.gz .
```

#### 3. Deploy to a fresh Pi

The target Pi needs:
- Raspberry Pi OS Bookworm (stock, no extra setup)
- SSH enabled (turn on during Raspberry Pi Imager flashing, or via `raspi-config`)
- SSH key auth configured from your dev machine
- Network connectivity (Ethernet, Wi-Fi, or USB gadget — see [Connectivity](#connectivity) below)

```bash
# Full first-time deploy — uploads bundle, installs deps, starts service
./deploy.sh pi-01.local

# Deploy to more Pis
./deploy.sh pi-02.local
./deploy.sh pi-03.local
```

#### 4. Push code updates

After making source code changes, push them to deployed Pis without re-uploading the full bundle:

```bash
# Syncs only src/ (~24KB), restarts service — takes seconds
./deploy.sh pi-01.local --update
./deploy.sh pi-02.local --update
```

#### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OAKD_USER` | `pi` | SSH user on the target Pi |
| `BUNDLE` | `./oakd-capture-bundle.tar.gz` | Path to the bundle tarball |

### Option B: Manual setup (single Pi)

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

Saved to `~/recordings/YYYYMMDD_HHMMSS/` on the Pi (timestamps are UTC):

```
~/recordings/
└── 20260130_143052/
    ├── recording_20260130_143052.mcap    # RGB + depth + IMU
    ├── calibration_20260130_143052.json  # camera intrinsics/extrinsics
    └── metadata_20260130_143052.json     # recording config + device info
```

MCAP payloads are raw binary — H.265 video frames and 48-byte packed IMU structs (6 little-endian doubles: ax, ay, az, gx, gy, gz). The recording is fsynced to disk every 5 seconds to limit data loss on hard power cuts.

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
├── bundle.sh                   # Create deployable tarball
├── deploy.sh                   # Deploy to Pis over SSH
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
