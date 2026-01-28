# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- DepthAI Sync node for RGB/left/right/IMU alignment (with fallback if unavailable)
- Disk-space guard before starting a recording
- Short drain window on stop to flush queued packets

### Changed
- On-device H.264 encoding for RGB/left/right to reduce host CPU
- Blocking queue reads with timeout and periodic warnings
- MCAP payload schema now stores H.264 bytes (custom schema)

## [0.1.1] - 2026-01-28

### Fixed
- Thread-safe recording stop (button callback no longer causes race condition)
- MCAP now uses Foxglove-compatible schemas (foxglove.CompressedImage, foxglove.Imu)
- Images encoded as JPEG for Foxglove Studio compatibility
- Use device timestamps instead of wall-clock time for accurate multi-stream alignment
- Fix metadata session_start to record actual session creation time, not cleanup time
- Fix bare `except:` to `except Exception:` to avoid catching SystemExit/KeyboardInterrupt
- Correct PROJECT_SPEC.md to match actual resolution (640x360) and IMU rate (100Hz)
- Fix __init__.py version to match pyproject.toml (0.1.1)

### Added
- docs/pi_setup.md - complete Pi setup guide (uv, systemd)
- opencv-python-headless dependency for JPEG encoding
- lgpio dependency for GPIO on newer kernels

### Changed
- Reduced camera resolutions for USB bandwidth (640x360 RGB, 640x400 mono)
- Use non-blocking beep_async for recording start/stop feedback
- Remove unused device_id variable

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
