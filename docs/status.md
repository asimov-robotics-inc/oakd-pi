# Project Status

## Milestones

### Completed
- **M1: Project Setup** - Project structure, pyproject.toml, documentation
- **M2: Core Implementation** - hardware.py + main.py
- **M3: Deployment** - systemd service file
- **M4: Testing & Fixes** - Thread-safe recording, Pi setup docs
- **M5: Raw Binary Format** - Drop Foxglove schemas, write raw H.265 + packed IMU bytes
- **M6: no_ux branch** - Remove button/buzzer hardware, auto-record on startup
- **M7: Setup scripts & doc cleanup** - Add setup.sh/run.sh/stop.sh, strip button/buzzer from all docs

- **M9: Crash-Safe Recording** - Periodic fsync + early metadata write to survive hard power cuts
- **M10: Boot Speed & Robustness** - Faster systemd startup, direct venv exec, tighter shutdown timeout
- **M11: Depth Preset Alignment** - Recorder now uses StereoDepth DEFAULT preset + subpixel(3-bit), removing manual depth filter overrides for viewer-like density
- **M12: Encoded Stereo Capture** - Switched to RGB 720p H.265 + mono 800p MJPEG with IMU 100Hz (no on-device depth)

### Upcoming
(none)
