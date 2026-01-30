# Raspberry Pi 5 Setup Guide

This guide walks through setting up the OAK-D capture system on a Raspberry Pi 5
with a monitor, keyboard, and mouse connected directly. It assumes you've already
flashed the OS and cloned the repo.

## Prerequisites

- Raspberry Pi 5 with Raspberry Pi OS booted and working
- Monitor + keyboard + mouse connected to the Pi
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

## 5. Retrieve Recordings

Recordings are saved to `~/recordings/` on the Pi. Each session gets its own
timestamped folder.

```bash
# list recording sessions
ls -la ~/recordings/
```

Each folder contains:
- `recording_YYYYMMDD_HHMMSS.mcap` - sensor data (RGB + depth + IMU)
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
- RGB: 1280x720
- Depth: aligned to RGB

If errors persist, try a powered USB hub or reduce FPS/resolution.
