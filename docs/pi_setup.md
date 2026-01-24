# Raspberry Pi Setup Guide

This guide covers setting up a Raspberry Pi 4 for the OAK-D capture system.

## 1. USB Gadget Mode (Connect via USB-C)

This lets you SSH and transfer files over the USB-C cable (no WiFi/Ethernet needed).

### On the Pi (one-time setup)

Edit `/boot/firmware/config.txt` and add at the end:

```
dtoverlay=dwc2
```

Edit `/boot/firmware/cmdline.txt` and add after `rootwait`:

```
modules-load=dwc2,g_ether
```

Reboot the Pi.

### On your PC

After connecting USB-C, the Pi appears as a network device with IP `192.168.5.18` (or similar).

```bash
# SSH in
ssh pi@192.168.5.18

# Copy files to Pi
scp file.txt pi@192.168.5.18:~/

# Copy files from Pi
scp pi@192.168.5.18:~/recordings/session_xxx ~/Downloads/
```

## 2. Install uv (Python package manager)

On the Pi:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
```

Verify:

```bash
uv --version
```

## 3. Deploy the Project

### Copy project files to Pi

From your PC:

```bash
scp -r /path/to/oakd-pi pi@192.168.5.18:~/
```

### Install dependencies

On the Pi:

```bash
cd ~/oakd-pi
uv sync
```

### Test manually

```bash
uv run python -m oakd_capture
```

You should hear 3 beeps when ready. Press button to start/stop recording.

## 4. Run on Boot (systemd)

### Install service

```bash
sudo cp ~/oakd-pi/systemd/oakd-capture.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable oakd-capture
```

### Start now

```bash
sudo systemctl start oakd-capture
```

### Check status

```bash
sudo systemctl status oakd-capture
```

### View logs

```bash
journalctl -u oakd-capture -f
```

### Stop/restart

```bash
sudo systemctl stop oakd-capture
sudo systemctl restart oakd-capture
```

## 5. Retrieve Recordings

Recordings are saved to `~/recordings/` on the Pi.

```bash
# List sessions
ssh pi@192.168.5.18 "ls -la ~/recordings/"

# Copy a session to your PC
scp -r pi@192.168.5.18:~/recordings/session_YYYYMMDD_HHMMSS ~/Downloads/
```

Each session contains:
- `recording_XXX.mcap` - sensor data (viewable in Foxglove Studio)
- `calibration.json` - camera intrinsics/extrinsics
- `metadata.json` - session info

## Troubleshooting

### USB connection not working

- Ensure USB-C cable supports data (not charge-only)
- Check `ip addr` on Pi for usb0 interface
- Try `ping 192.168.5.18` from PC

### GPIO errors

If you see "Failed to add edge detection", ensure `lgpio` is installed:

```bash
uv add lgpio
```

### Camera bandwidth errors (X_LINK_ERROR)

The Pi 4 has limited USB bandwidth. The current config uses reduced resolutions:
- RGB: 640x360
- Mono: 640x400

If errors persist, try a powered USB hub or reduce FPS.
