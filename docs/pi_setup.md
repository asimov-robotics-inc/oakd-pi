# Raspberry Pi 5 Setup Guide

This guide walks through setting up the OAK-D capture system on a Raspberry Pi 5
with a monitor, keyboard, and mouse connected directly. It assumes you've already
flashed the OS and cloned the repo.

## Prerequisites

- Raspberry Pi 5 with Raspberry Pi OS booted and working
- Monitor + keyboard + mouse connected to the Pi
- This repo already cloned to `~/oakd-pi`
- OAK-D Pro + USB-C data cable
- Momentary push button
- Active buzzer (3.3V)
- Jumper wires (female-to-female)

## 1. Wiring

### GPIO Pinout (Pi 5 40-pin header)

Looking at the Pi with the USB ports facing you, pin 1 is top-left:

```
           3V3 Power  (1)  (2)  5V Power
          GPIO 2/SDA  (3)  (4)  5V Power
          GPIO 3/SCL  (5)  (6)  GND
              GPIO 4  (7)  (8)  GPIO 14
                 GND  (9)  (10) GPIO 15
    BUTTON -> GPIO 17 (11) (12) GPIO 18 <- BUZZER
             GPIO 27  (13) (14) GND <- BUZZER GND
             GPIO 22  (15) (16) GPIO 23
           3V3 Power  (17) (18) GPIO 24
             GPIO 10  (19) (20) GND
              GPIO 9  (21) (22) GPIO 25
             GPIO 11  (23) (24) GPIO 8
         BUTTON GND   (25) (26) GPIO 7
              ...remaining pins...
```

### Button (2 wires)

The momentary push button connects to GPIO 17. The software uses an internal
pull-up resistor, so no external resistor is needed.

| Wire | From          | To (Pi pin)              |
|------|---------------|--------------------------|
| 1    | Button leg A  | **Pin 11** (GPIO 17)     |
| 2    | Button leg B  | **Pin 25** (GND)         |

> If your button has 4 legs, the two legs on the same side are connected
> internally. Use one leg from each side.

### Buzzer (2 wires)

The active buzzer (the kind that beeps when you apply voltage, no frequency
generation needed) connects to GPIO 18.

| Wire | From       | To (Pi pin)              |
|------|------------|--------------------------|
| 1    | Buzzer (+) | **Pin 12** (GPIO 18)     |
| 2    | Buzzer (-) | **Pin 14** (GND)         |

> Active buzzers have a (+) marking or a longer leg. Polarity matters.

### OAK-D Pro (1 cable)

Plug the OAK-D Pro's USB-C cable into one of the Pi 5's **blue USB 3.0 ports**
(not the black USB 2.0 ports). USB 3.0 is needed for camera bandwidth.

### Power

Plug a USB-C cable from your laptop into the Pi 5's **USB-C power port** (the
port between the micro-HDMI ports and the audio jack).

### Summary

```
Pi 5 Pin 11 (GPIO 17) ---- Button ---- Pi 5 Pin 25 (GND)
Pi 5 Pin 12 (GPIO 18) ---- Buzzer + -- Pi 5 Pin 14 (GND)
Pi 5 USB 3.0 port -------- OAK-D Pro USB-C
Pi 5 USB-C power port ---- Laptop USB-C (power)
```

## 2. Connect to WiFi (if not already connected)

Open a terminal on the Pi and connect to your network:

```bash
sudo nmcli device wifi connect "YOUR_SSID" password "YOUR_PASSWORD"
```

Verify the connection:

```bash
ip addr show wlan0
```

You should see an IP address assigned. WiFi is needed for installing packages.

## 3. System Setup

Open a terminal and run these commands:

```bash
# update the system
sudo apt update && sudo apt upgrade -y

# install dependencies for depthai and usb camera access
sudo apt install -y git python3-dev libusb-1.0-0-dev libopenblas-dev

# add udev rules for OAK-D (allows non-root USB access)
echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", MODE="0666"' | \
  sudo tee /etc/udev/rules.d/80-movidius.rules
sudo udevadm control --reload-rules && sudo udevadm trigger

# install uv (python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc

# verify
uv --version
```

## 4. Install the Project

```bash
cd ~/oakd-pi
uv sync
```

This installs Python 3.11 (managed by uv) and all project dependencies.

## 5. Verify OAK-D is Detected

With the OAK-D plugged into a blue USB 3.0 port:

```bash
uv run python -c "import depthai; print(depthai.Device.getAllAvailableDevices())"
```

You should see at least one device listed.

## 6. Test the Capture

```bash
uv run python -m oakd_capture
```

- 3 beeps = ready
- Press button = start recording (1 beep)
- Press button again = stop recording (2 beeps)

## 7. Run on Boot (systemd)

```bash
sudo cp ~/oakd-pi/systemd/oakd-capture.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable oakd-capture
sudo systemctl start oakd-capture
```

Check status:

```bash
sudo systemctl status oakd-capture
```

View logs:

```bash
journalctl -u oakd-capture -f
```

Stop or restart:

```bash
sudo systemctl stop oakd-capture
sudo systemctl restart oakd-capture
```

## 8. Retrieve Recordings

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

### GPIO errors

If you see "Failed to add edge detection":

```bash
uv add lgpio
```

### Camera bandwidth errors (X_LINK_ERROR)

Use the blue USB 3.0 ports, not USB 2.0. The current config uses:
- RGB: 1280x720
- Depth: aligned to RGB

If errors persist, try a powered USB hub or reduce FPS/resolution.
