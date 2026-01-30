# Changelog

All notable changes to this project will be documented in this file.

## [0.4.0] - 2026-01-29

### Changed
- Auto-record on startup: recording begins immediately when pipeline is ready
- Recording runs continuously until SIGTERM/SIGINT shutdown

### Removed
- Button and buzzer hardware support (hardware.py deleted)
- `gpiozero` and `lgpio` dependencies
- `_on_button_press` callback and `_stop_requested` flag

## [0.3.2] - 2026-01-29

### Changed
- Rewrote pi_setup.md for local keyboard/mouse setup (no SSH-first assumption)
- Simplified README quick start to reference setup guide
- Fixed README references from H.264 to H.265

## [0.3.1] - 2026-01-29

### Added
- On-device StereoDepth output (RGB-aligned) recorded to MCAP
- Expanded recording metadata (fps, resolution, depth settings, IMU rate)
- Disk-space guard before starting a recording
- Short drain window on stop to flush queued packets

### Changed
- Recordings now stored in per-recording timestamp folders (UTC)
- Only RGB + depth + IMU are recorded (no left/right mono outputs)
- Main loop uses blocking sync queue with timeouts and batches IMU reads
- systemd service auto-restarts more aggressively for reliability

### Removed
- Foxglove schema definitions (CompressedVideo, Imu)
- base64 dependency for frame encoding

## [0.3.0] - 2026-01-29

### Changed
- McapRecorder uses raw binary format instead of Foxglove JSON schemas
- Video frames written as raw H.265 bytes (no base64/JSON wrapping)
- IMU data packed as 48-byte binary (6 little-endian doubles: ax,ay,az,gx,gy,gz)
- Recording config stored as MCAP metadata (resolution, fps, encoding, imu_hz)

## [0.2.0] - 2026-01-24

### Added
- Sync node for camera stream synchronization (<10ms threshold)
- Device timestamps for all frames (not system time)
- IMU at 200Hz (was 100Hz)

### Changed
- H.265 encoding on camera (industry standard, 10 Mbps)
- All cameras at 720p @ 30fps (unified resolution)
- Removed opencv dependency (encoding now on-device)
- Only synchronized frame groups are saved (RGB + left + right aligned)

## [0.1.1] - 2026-01-24

### Fixed
- Thread-safe recording stop (button callback no longer causes race condition)
- MCAP now uses Foxglove-compatible schemas (foxglove.CompressedVideo, foxglove.Imu)

### Added
- docs/pi_setup.md - complete Pi setup guide (Wi-Fi SSH, local setup, systemd)
- lgpio dependency for GPIO on newer kernels

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
