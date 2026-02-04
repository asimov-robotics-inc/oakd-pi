# OAK-D Pi Egocentric Data Capture Kit

## Project Goal

Build a high-quality egocentric data capture device for training robots. The system runs headlessly on a Raspberry Pi with an OAK-D Pro camera, auto-recording on startup. Data is saved in MCAP format for offline processing by robotics companies (1X, Figure, Physical Intelligence, Persona AI, etc.).

## Hardware

- Raspberry Pi (with SD card storage)
- OAK-D Pro (will eventually swap for OAK-D Pro W)
- Battery pack

## Functional Requirements

### Boot Behavior
- Script runs automatically on Pi boot via systemd
- Recording begins immediately when pipeline is ready

### Recording Control
- Recording starts automatically on startup
- Recording stops on SIGTERM/SIGINT (shutdown or service stop)
- Each recording gets its own timestamped folder

### Data Capture
- RGB camera: H.265 @ 720p, 30fps
- Mono left/right: MJPEG @ 800p, 30fps
- IMU: 100Hz accelerometer + gyroscope
- IR projector: Enabled at 50% intensity
- RGB + mono synchronized via device Sync node

### Output Format
- MCAP files (industry standard, Foxglove/ROS compatible)
- Calibration data saved per recording
- Recording metadata (device info, timestamps, config)

## Recording Structure

```
~/recordings/
└── YYYYMMDD_HHMMSS/
    ├── recording_YYYYMMDD_HHMMSS.mcap
    ├── calibration_YYYYMMDD_HHMMSS.json
    └── metadata_YYYYMMDD_HHMMSS.json
```

## Technical Stack

- Python 3.11
- DepthAI SDK v3 for camera control and MCAP recording
- systemd for autostart
