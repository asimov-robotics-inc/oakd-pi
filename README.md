# OAK-D Egocentric Capture

Headless data capture system for robotics training using Raspberry Pi 5 + OAK-D Pro.

## Features

- RGB camera (720p @ 30fps, H.265)
- Depth (StereoDepth on-device, RGB-aligned)
- IMU (200Hz accelerometer + gyroscope)
- IR projector for improved depth
- On-device H.265 encoding (10 Mbps, near-lossless)
- **Software-synchronized** RGB + depth (Sync node, <10ms threshold)
- Device timestamps for all streams
- Auto-record on startup
- MCAP format (raw binary H.265 + packed IMU)
- Runs on boot via systemd

## Hardware

- Raspberry Pi 5
- OAK-D Pro (USB-C)
- USB-C cable for Pi connection

## Quick Start

See [Pi Setup Guide](docs/pi_setup.md) for full first-time setup.

```bash
cd ~/oakd-pi

# Install system deps, uv, and project packages
./setup.sh

# Run manually
uv run python -m oakd_capture
```

Recording begins automatically on startup.

## Run on Boot

```bash
# Enable and start the systemd service
./run.sh

# Stop and disable
./stop.sh
```

## Recordings

Saved to `~/recordings/YYYYMMDD_HHMMSS/` (timestamp is UTC):
- `recording_YYYYMMDD_HHMMSS.mcap` - sensor data (RGB + depth + IMU)
- `calibration_YYYYMMDD_HHMMSS.json` - camera intrinsics/extrinsics
- `metadata_YYYYMMDD_HHMMSS.json` - recording config + device info

MCAP payloads contain raw H.265 video frames and 48-byte packed IMU binary. Not Foxglove-compatible out of the box.

## Documentation

- [Pi Setup Guide](docs/pi_setup.md) - detailed setup instructions
- [Project Spec](PROJECT_SPEC.md) - full specification
- [Changelog](docs/changelog.md) - version history
