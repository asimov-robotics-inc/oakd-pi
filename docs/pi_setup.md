# Raspberry Pi 5 Setup Guide

This guide covers setting up a fresh Raspberry Pi 5 for the OAK-D capture system.

## What You Need

- Raspberry Pi 5
- microSD card (will be wiped)
- USB-C cable (laptop to Pi for power)
- OAK-D Pro + USB-C data cable
- Momentary push button
- Active buzzer (3.3V)
- 3x female-to-female jumper cables
- A laptop on the same WiFi network

## 1. Flash the microSD Card

Download and open [Raspberry Pi Imager](https://www.raspberrypi.com/software/).

1. **Device**: Raspberry Pi 5
2. **OS**: Raspberry Pi OS Lite (64-bit, Bookworm) — no desktop needed for headless use
3. **Storage**: Select your microSD card

Before flashing, click **Edit Settings** (gear icon) to pre-configure:

| Setting            | Value                          |
|--------------------|--------------------------------|
| Hostname           | `pi`                           |
| Enable SSH         | Yes (use password or paste your public key) |
| Username           | `pi`                           |
| Password           | `pi`                           |
| WiFi SSID          | (your network name)            |
| WiFi Password      | (your network password)        |
| WiFi Country       | (your country code, e.g. US)   |
| Timezone           | (your timezone)                |

Flash the card. This wipes everything on it.

> **Note:** The Pi 5's USB-C port is power-only (no USB gadget/OTG mode like the
> Pi 4). You cannot access the Pi over the USB cable — WiFi + SSH is required.

## 2. Wiring

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

## 3. First Boot

1. Insert the flashed microSD card
2. Plug in the USB-C power cable from your laptop
3. Wait ~60 seconds for the Pi to boot and connect to WiFi

Then from your laptop:

```bash
# SSH in (Bonjour)
ssh pi@pi.local

# Or use the IP directly
ssh pi@192.168.5.18

# Copy files to Pi
scp file.txt pi@192.168.5.18:~/

# Copy files from Pi
scp -r pi@192.168.5.18:~/recordings/20260129_123456 ~/Downloads/
```

If `pi.local` doesn't resolve, check your router's admin page for the
Pi's IP address and use that instead.

### If you need to configure WiFi after first boot

If you forgot to set WiFi in Pi Imager, connect a monitor + keyboard and run:

```bash
sudo nmcli device wifi connect "YOUR_SSID" password "YOUR_PASSWORD"
```

Verify:

```bash
ip addr show wlan0
```

## 4. System Setup

Run these commands on the Pi:

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

## 5. Clone and Install the Project

```bash
cd ~
git clone https://github.com/asimov-robotics-inc/oakd-pi.git
cd oakd-pi
uv sync
```

## 6. Verify OAK-D is Detected

With the OAK-D plugged into a blue USB 3.0 port:

```bash
uv run python -c "import depthai; print(depthai.Device.getAllAvailableDevices())"
```

You should see at least one device listed.

## 7. Test the Capture

```bash
uv run python -m oakd_capture
```

- 3 beeps = ready
- Press button = start recording (1 beep)
- Press button again = stop recording (2 beeps)

## 8. Run on Boot (systemd)

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

## 9. Retrieve Recordings

Recordings are saved to `~/recordings/` on the Pi.

```bash
# list sessions
ssh pi@pi.local "ls -la ~/recordings/"

# Copy a recording to your PC
scp -r pi@192.168.5.18:~/recordings/YYYYMMDD_HHMMSS ~/Downloads/
```

Each recording folder contains:
- `recording_YYYYMMDD_HHMMSS.mcap` - sensor data (viewable in Foxglove Studio)
- `calibration_YYYYMMDD_HHMMSS.json` - camera intrinsics/extrinsics
- `metadata_YYYYMMDD_HHMMSS.json` - recording config + device info

## Troubleshooting

### Can't SSH / Pi not on network

- Double-check WiFi credentials were set in Pi Imager
- Try connecting a monitor + keyboard to configure WiFi manually (see step 3)
- Make sure your laptop is on the same network

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
