# OAK-D Egocentric Capture

Headless data capture system for robotics training. Raspberry Pi 5 + OAK-D Pro records synchronized RGB, left/right monochrome, and IMU streams to MCAP format. Starts recording on boot, no screen or keyboard needed. If the camera isn't available at boot, the app keeps retrying until it is.

## What it captures

| Stream | Details |
|--------|---------|
| RGB | 720p @ 30fps, H.265 encoded on-camera (6 Mbps) |
| Mono Left | 800p @ 30fps, MJPEG encoded on-camera (quality 90) |
| Mono Right | 800p @ 30fps, MJPEG encoded on-camera (quality 90) |
| IMU | 200Hz accelerometer + gyroscope |
| IR | Dot projector at 50% for improved texture |

RGB and mono streams are synchronized on-device via the Sync node. Timestamps come from the device clock, not the Pi.

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
    ├── recording_20260130_143052.mcap    # RGB + left/right mono + IMU
    ├── calibration_20260130_143052.json  # camera intrinsics/extrinsics
    └── metadata_20260130_143052.json     # recording config + device info
```

MCAP payloads are raw binary — H.265 video frames (RGB), MJPEG frames (left/right mono), and 48-byte packed IMU structs (6 little-endian doubles: ax, ay, az, gx, gy, gz). The recording is fsynced to disk every 5 seconds to limit data loss on hard power cuts.

## Reliability and failure modes

This system is designed for headless capture with bounded data loss and clear recovery behavior.

### Power loss / hard unplug
- The MCAP file is **fsynced every 5 seconds**, so **data loss is typically limited to a few seconds**.
- Recordings are **segmented every 10 minutes**, so **file corruption is limited to the active segment**.
- Metadata + calibration are written at segment start and fsynced, so they survive power cuts.

### Camera unplug / USB disconnect
- If the OAK‑D is unplugged, the pipeline errors out, the app **closes the current segment**, and enters a retry loop.
- The app retries device init every 5 seconds; when the camera returns it **starts a new segment** automatically.

### Disk full
- The app checks free disk space before each new segment and periodically while recording.
- If free space is below the threshold, it **stops recording** to avoid corrupt writes.

### CPU or USB bandwidth saturation
- RGB and mono streams are encoded on‑device; IMU is lightweight.
- If FPS drops, common fixes are lowering mono resolution/FPS or reducing RGB bitrate.

### `fsync()` (why it matters)
- `fsync()` forces buffered data to be written to disk immediately.
- It trades a small amount of I/O overhead for **predictable, bounded data loss** on power cuts.

## Offline processing

Depth is computed offline from the recorded mono pair if needed. For downstream use:

1) **Demux and decode**
   - Decode H.265 frames for `rgb`.
   - Decode MJPEG frames for `left` and `right`.
2) **Stereo usage**
   - Rectify mono frames using the calibration file.
   - Run your stereo model (e.g., FoundationStereo/IGEV) on the rectified pair.
3) **IMU alignment**
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
