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

## 4.1 Updating the Pi

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
