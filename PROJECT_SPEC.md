# OAK-D Pi Egocentric Data Capture Kit

## Project Goal

Build a high-quality egocentric data capture device for training robots. The system runs headlessly on a Raspberry Pi with an OAK-D Pro camera, using a button for start/stop control and a buzzer for audio feedback. Data is saved in MCAP format for offline processing by robotics companies (1X, Figure, Physical Intelligence, Persona AI, etc.).

## Hardware

- Raspberry Pi (with SD card storage)
- OAK-D Pro (will eventually swap for OAK-D Pro W)
- Button (GPIO 17) - start/stop recording
- Buzzer (GPIO 18) - audio feedback
- Battery pack

## Functional Requirements

### Boot Behavior
- Script runs automatically on Pi boot via systemd
- 3 beeps when device is ready to record

### Recording Control
- Button press starts recording (1 beep)
- Button press stops recording (2 beeps)
- Multiple recordings per session supported

### Data Capture
- RGB camera: MJPEG @ 720p, 30fps
- Stereo mono cameras: Raw @ 400p, 30fps
- IMU: 400Hz accelerometer + gyroscope
- IR projector: Enabled at 50% intensity
- All streams temporally synchronized via DepthAI Sync node

### Output Format
- MCAP files (industry standard, Foxglove/ROS compatible)
- Calibration data saved per session
- Session metadata (device info, timestamps)

## Recording Structure

```
~/recordings/
└── session_YYYYMMDD_HHMMSS/
    ├── recording_001.mcap
    ├── recording_002.mcap
    ├── calibration.json
    └── metadata.json
```

## Technical Stack

- Python 3.11
- DepthAI SDK v3 for camera control and MCAP recording
- gpiozero for button/buzzer GPIO
- systemd for autostart

## Audio Feedback

| Event | Beeps |
|-------|-------|
| Device ready | 3 |
| Recording started | 1 |
| Recording stopped | 2 |
| Error | Long beep |
