# Changelog

All notable changes to this project will be documented in this file.

## [0.1.1] - 2026-01-24

### Fixed
- Thread-safe recording stop (button callback no longer causes race condition)
- MCAP now uses Foxglove-compatible schemas (foxglove.CompressedImage, foxglove.Imu)
- Images encoded as JPEG for Foxglove Studio compatibility

### Added
- docs/pi_setup.md - complete Pi setup guide (USB gadget, uv, systemd)
- opencv-python-headless dependency for JPEG encoding
- lgpio dependency for GPIO on newer kernels

### Changed
- Reduced camera resolutions for USB bandwidth (640x360 RGB, 640x400 mono)

## [0.1.0] - 2026-01-24

### Added
- Initial project structure with uv/pyproject.toml
- hardware.py: Button and buzzer control via gpiozero
  - 3 beeps on ready, 1 on start, 2 on stop
  - Button debounce and cooldown
  - Inverted logic for active buzzers
- main.py: Camera pipeline and recording
  - RGB camera at 720p/30fps (MJPEG)
  - Stereo mono cameras at 400p/30fps
  - IMU at 100Hz
  - IR projector at 50% intensity
  - MCAP recording with calibration and metadata
- systemd/oakd-capture.service for autostart
- PROJECT_SPEC.md, CLAUDE.md, docs/
