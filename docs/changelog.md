# Changelog

All notable changes to this project will be documented in this file.

## [0.5.1] - 2026-01-31

### Added
- Recording rotation every 10 minutes for better resilience to hard power cuts
- Periodic disk space checks during recording
- Durable fsync of metadata and calibration files
- Device init retry loop to keep recording attempts alive until the camera is available

### Changed
- systemd now restarts indefinitely without start-limit throttling
- Replaced on-device depth recording with stereo left/right H.265 streams (depth computed offline)
- Aligned RGB/L/R by sequence number instead of Sync node to avoid frame drops

### Removed
- Bundle-based deployment scripts; manual setup is now the only supported path
- Removed local MCAP viewer tooling and dependencies

## [0.5.0] - 2026-01-30

### Added
- `bundle.sh` - creates portable `oakd-capture-bundle.tar.gz` from a configured Pi (pre-built .venv + source + systemd + embedded install.sh)
- `deploy.sh` - SSH-based deployment from dev machine: full first-deploy (`./deploy.sh <host>`) and fast source-only update (`./deploy.sh <host> --update`)

### Changed
- Rewrote README with comprehensive deployment guide, connectivity options (Ethernet, Wi-Fi, USB gadget), service management, and recording retrieval
- Updated pi_setup.md to note bundle deploy as preferred alternative for multi-Pi setups

## [0.4.4] - 2026-01-30

### Changed
- systemd service starts after `local-fs.target` instead of `multi-user.target` (no longer waits for networking)
- ExecStart uses `.venv/bin/python` directly instead of `uv run`, eliminating venv resolution overhead on every boot
- Reduced `TimeoutStopSec` from 30s to 10s (app shuts down in under a second)
- Increased `StartLimitIntervalSec` from 30s to 60s for more restart headroom during early boot

## [0.4.3] - 2026-01-30

### Changed
- MCAP file is fsynced to disk every 5 seconds, limiting data loss on hard power cut to ~5s of frames
- JSON metadata is written at recording start instead of only on clean shutdown

### Added
- `McapRecorder.flush()` method for periodic fsync of the recording file

## [0.4.2] - 2026-01-30

### Added
- `tools/viewer.py` - standalone MCAP recording viewer with RGB video, depth colormap, and scrolling IMU plot
- Optional `viewer` dependency group in pyproject.toml (`opencv-python`, `av`, `numpy`)

## [0.4.1] - 2026-01-30

### Added
- `setup.sh` - one-command system setup (apt deps, udev rules, uv, uv sync)
- `run.sh` - install, enable, and start systemd service
- `stop.sh` - stop and disable systemd service

### Changed
- Rewrote `docs/pi_setup.md`: removed wiring/button/buzzer sections, replaced manual setup steps with `./setup.sh`, replaced systemd commands with `./run.sh` / `./stop.sh`
- Rewrote `README.md`: removed button/buzzer from features/hardware, updated quick start to use `setup.sh`, updated run-on-boot to use `run.sh`/`stop.sh`
- Updated `PROJECT_SPEC.md`: removed button/buzzer/gpiozero references, updated to auto-record behavior

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
