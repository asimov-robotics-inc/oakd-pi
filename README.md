# OAK-D Egocentric Capture

Headless data capture system for robotics training using Raspberry Pi 4 + OAK-D Pro.

## Features

- RGB camera (640x360 @ 30fps)
- Stereo mono cameras (640x400 @ 30fps)
- IMU (100Hz accelerometer + gyroscope)
- IR projector for improved depth
- Button start/stop with buzzer feedback
- MCAP format (Foxglove Studio compatible)
- Runs on boot via systemd

## Hardware

- Raspberry Pi 4
- OAK-D Pro (USB-C)
- Momentary button (GPIO 17)
- Active buzzer (GPIO 18)
- USB-C cable for Pi connection

## Quick Start

```bash
# SSH into Pi
ssh pi@192.168.5.18

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone/copy project
git clone https://github.com/asimov-robotics-inc/oakd-pi.git
cd oakd-pi

# Install dependencies
uv sync

# Run
uv run python -m oakd_capture
```

3 beeps = ready. Press button to start/stop recording.

## Recordings

Saved to `~/recordings/session_YYYYMMDD_HHMMSS/`:
- `recording_XXX.mcap` - sensor data
- `calibration.json` - camera intrinsics
- `metadata.json` - session info

View in [Foxglove Studio](https://foxglove.dev/studio).

## Run on Boot

```bash
sudo cp systemd/oakd-capture.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable oakd-capture
sudo systemctl start oakd-capture
```

## Documentation

- [Pi Setup Guide](docs/pi_setup.md) - detailed setup instructions
- [Project Spec](PROJECT_SPEC.md) - full specification
- [Changelog](docs/changelog.md) - version history
