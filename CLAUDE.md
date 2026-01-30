# OAK-D Pi Capture Kit

Headless egocentric data capture system for robotics training data. Runs on Raspberry Pi with OAK-D Pro, captures synchronized RGB/stereo/IMU streams to MCAP format.

## Project Structure

```
oakd-pi/
├── pyproject.toml
├── .python-version
├── PROJECT_SPEC.md          # Full specification
├── docs/
│   ├── status.md            # Milestone tracking
│   └── changelog.md         # Version history
├── setup.sh                 # System setup (deps, udev, uv)
├── run.sh                   # Enable + start systemd service
├── stop.sh                  # Stop + disable systemd service
├── src/oakd_capture/
│   ├── __init__.py
│   ├── __main__.py          # Entry point
│   └── main.py              # App orchestration, camera, recording
└── systemd/
    └── oakd-capture.service
```

## Core Workflow

You MUST update `docs/status.md` and `docs/changelog.md` before every commit or push to reflect current progress and changes.
