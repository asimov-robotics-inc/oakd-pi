"""Main application: camera pipeline, recording, and state machine using depthai v3."""

import signal
import logging
import json
import os
import struct
import time
import shutil
from enum import Enum, auto
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional

import depthai as dai
import lz4.frame as lz4f
from mcap.writer import Writer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
log = logging.getLogger(__name__)

# Configuration
RECORDINGS_DIR = Path.home() / "recordings"
CAMERA_FPS = 30  # All cameras synced at same FPS
IMU_HZ = 200  # IMU sample rate
IR_INTENSITY = 0.5
MIN_FREE_GB = 2.0
SEGMENT_MINUTES = 10
DISK_CHECK_INTERVAL_S = 60.0
DEVICE_RETRY_INTERVAL_S = 5.0

# Video encoding settings (H.265 on camera)
RESOLUTION = (640, 480)  # 480p for all cameras
H265_BITRATE = 6_000_000  # 6 Mbps - high quality for 480p

# Synchronization settings
SYNC_METHOD = "device_sync_node"
SYNC_THRESHOLD_MS = 10
FSYNC_INTERVAL_S = 5.0  # Flush MCAP to disk every N seconds


class State(Enum):
    INITIALIZING = auto()
    READY = auto()
    RECORDING = auto()
    SHUTTING_DOWN = auto()


class McapRecorder:
    """MCAP file recorder with raw binary format (no schemas)."""

    def __init__(self, filepath: Path):
        self._filepath = filepath
        self._file = None
        self._writer = None
        self._channels = {}

    def open(self):
        """Open MCAP file for writing."""
        self._file = open(self._filepath, "wb")
        self._writer = Writer(self._file)
        self._writer.start()

        # Register channels (raw bytes, no schema)
        for topic_name in ("rgb", "depth", "imu"):
            self._channels[topic_name] = self._writer.register_channel(
                topic=f"/oak/{topic_name}",
                message_encoding="",
                schema_id=0,
            )

        # Store recording parameters as MCAP metadata
        self._writer.add_metadata(
            "recording_config",
            {
                "resolution": f"{RESOLUTION[0]}x{RESOLUTION[1]}",
                "fps": str(CAMERA_FPS),
                "video_encoding": "h265",
                "imu_hz": str(IMU_HZ),
                "sync_method": SYNC_METHOD,
                "sync_threshold_ms": str(SYNC_THRESHOLD_MS),
                "timestamp_source": "device",
                "depth_encoding": "raw16_mm_lz4",
                "depth_compression": "lz4frame",
            },
        )
        log.info(f"Opened MCAP: {self._filepath}")

    def write_frame(self, channel_name: str, data: bytes, timestamp_ns: int):
        """Write raw H.265 encoded frame bytes to the MCAP file."""
        if not self._writer or not self._file or channel_name not in self._channels:
            return

        self._writer.add_message(
            channel_id=self._channels[channel_name],
            log_time=timestamp_ns,
            publish_time=timestamp_ns,
            data=data,
        )

    def write_imu(self, imu_data: dai.IMUData):
        """Write IMU data as packed binary (6 doubles: ax,ay,az,gx,gy,gz = 48 bytes)."""
        if not self._writer or not self._file:
            return

        for packet in imu_data.packets:
            # Use accelerometer timestamp (both sensors are synced)
            ts_ns = int(packet.acceleroMeter.getTimestampDevice().total_seconds() * 1e9)
            data = struct.pack(
                "<6d",
                packet.acceleroMeter.x,
                packet.acceleroMeter.y,
                packet.acceleroMeter.z,
                packet.gyroscope.x,
                packet.gyroscope.y,
                packet.gyroscope.z,
            )
            self._writer.add_message(
                channel_id=self._channels["imu"],
                log_time=ts_ns,
                publish_time=ts_ns,
                data=data,
            )

    def flush(self):
        """Flush buffered data to disk so it survives a hard power cut."""
        if self._file and not self._file.closed:
            self._file.flush()
            os.fsync(self._file.fileno())

    def close(self):
        """Close the MCAP file."""
        if self._writer:
            self.flush()
            self._writer.finish()
            self._writer = None
        if self._file:
            self._file.close()
            self._file = None
        log.info(f"Closed MCAP: {self._filepath}")


class CaptureApp:
    """Main application orchestrating camera and recording (auto-record, no UX hardware)."""

    def __init__(self):
        self._state = State.INITIALIZING
        self._running = True
        self._device_id: Optional[str] = None
        self._device: Optional[dai.Device] = None
        self._recorder: Optional[McapRecorder] = None
        self._last_recording_ts: Optional[str] = None
        self._last_recording_dir: Optional[Path] = None
        self._last_queue_warn = {}
        self._segment_start_monotonic: Optional[float] = None
        self._last_disk_check = 0.0

        # Register signal handlers
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signals."""
        log.info(f"Received signal {signum}, shutting down...")
        self._running = False
        self._state = State.SHUTTING_DOWN

    def _ensure_recordings_dir(self, timestamp: str) -> Path:
        """Ensure recordings directory exists and create per-recording folder."""
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        recording_dir = RECORDINGS_DIR / timestamp
        recording_dir.mkdir(parents=True, exist_ok=True)
        return recording_dir

    def _save_calibration(self, device: dai.Device, recording_dir: Path, timestamp: str) -> None:
        """Save camera calibration data alongside recording."""
        try:
            calib = device.readCalibration()
            calib_path = recording_dir / f"calibration_{timestamp}.json"
            calib.eepromToJsonFile(str(calib_path))
            self._fsync_path(calib_path)
            log.info(f"Saved calibration to {calib_path}")
        except Exception as e:
            log.warning(f"Failed to save calibration: {e}")

    def _save_metadata(self, recording_dir: Path, timestamp: str, mcap_path: Path) -> None:
        """Save recording metadata."""
        try:
            metadata = {
                "recording_start": timestamp,
                "mcap_path": str(mcap_path),
                "device_id": self._device_id,
                "recording_config": {
                    "resolution": f"{RESOLUTION[0]}x{RESOLUTION[1]}",
                    "camera_fps": CAMERA_FPS,
                    "imu_hz": IMU_HZ,
                    "sync_method": SYNC_METHOD,
                    "sync_threshold_ms": SYNC_THRESHOLD_MS,
                    "timestamp_source": "device",
                    "ir_intensity": IR_INTENSITY,
                    "video_encoding": "h265",
                    "h265_bitrate": H265_BITRATE,
                    "depth": {
                        "aligned_to": "rgb",
                        "left_right_check": True,
                        "rectification": True,
                        "depth_encoding": "raw16_mm_lz4",
                        "depth_compression": "lz4frame",
                    },
                },
            }
            metadata_path = recording_dir / f"metadata_{timestamp}.json"
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            self._fsync_dir(recording_dir)
            log.info(f"Saved metadata to {metadata_path}")
        except Exception as e:
            log.warning(f"Failed to save metadata: {e}")

    def _fsync_dir(self, path: Path) -> None:
        """Force directory entry to disk so files survive hard power cuts."""
        try:
            fd = os.open(path, os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except Exception as e:
            log.warning(f"Failed to fsync dir {path}: {e}")

    def _fsync_path(self, path: Path) -> None:
        """Force file and its parent dir to disk."""
        try:
            with open(path, "rb") as f:
                os.fsync(f.fileno())
        except Exception as e:
            log.warning(f"Failed to fsync file {path}: {e}")
        self._fsync_dir(path.parent)

    def _check_disk_space(self) -> bool:
        """Return True if there's enough free space to record."""
        try:
            free_gb = shutil.disk_usage(RECORDINGS_DIR).free / (1024**3)
            if free_gb < MIN_FREE_GB:
                log.warning(f"Low disk space ({free_gb:.2f} GB free)")
                return False
            return True
        except Exception as e:
            log.warning(f"Disk space check failed: {e}")
            return True

    def _start_recording(self) -> None:
        """Start a new recording."""
        if not self._check_disk_space():
            log.warning("Refusing to start recording due to low disk space")
            return

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        recording_dir = self._ensure_recordings_dir(timestamp)
        mcap_path = recording_dir / f"recording_{timestamp}.mcap"
        self._last_recording_ts = timestamp
        self._last_recording_dir = recording_dir

        self._recorder = McapRecorder(mcap_path)
        self._recorder.open()
        if self._device:
            self._save_calibration(self._device, recording_dir, timestamp)

        # Write metadata immediately so it exists even after a hard power cut
        self._save_metadata(recording_dir, timestamp, mcap_path)

        log.info(f"Recording started: {mcap_path}")
        self._state = State.RECORDING
        self._segment_start_monotonic = time.monotonic()

    def _stop_recording(self) -> None:
        """Stop current recording."""
        self._state = State.READY
        self._segment_start_monotonic = None

        if self._recorder:
            self._recorder.close()
            self._recorder = None

        log.info("Recording stopped")

    def _drain_queue(self, queue, name: str):
        """Return all available items from a queue without blocking."""
        items = []
        try:
            items = queue.tryGetAll()
        except Exception:
            item = queue.tryGet()
            if item is not None:
                items = [item]
        if not items:
            now = time.monotonic()
            last = self._last_queue_warn.get(name, 0.0)
            if now - last > 5.0:
                log.warning(f"No data from {name} queue for >5s")
                self._last_queue_warn[name] = now
        return items

    def run(self) -> None:
        """Main application loop."""
        while self._running:
            device = None
            try:
                log.info("Initializing camera...")

                # Connect to device first to enable IR
                device = dai.Device()
                device_id = device.getMxId()  # Get ID before pipeline starts
                self._device_id = device_id
                self._device = device

                # Enable IR projector
                try:
                    device.setIrLaserDotProjectorIntensity(IR_INTENSITY)
                    device.setIrFloodLightIntensity(0.0)
                    log.info(f"IR projector enabled at {IR_INTENSITY * 100}%")
                except Exception as e:
                    log.warning(f"IR projector not available: {e}")

                # Create pipeline with device context (v3 API)
                with dai.Pipeline(device) as pipeline:
                    # RGB camera
                    cam_rgb = pipeline.create(dai.node.Camera).build(
                        boardSocket=dai.CameraBoardSocket.CAM_A,
                        sensorFps=CAMERA_FPS,
                    )

                    # Mono cameras for stereo (hardware synced via FSYNC)
                    cam_left = pipeline.create(dai.node.Camera).build(
                        boardSocket=dai.CameraBoardSocket.CAM_B,
                        sensorFps=CAMERA_FPS,
                    )

                    cam_right = pipeline.create(dai.node.Camera).build(
                        boardSocket=dai.CameraBoardSocket.CAM_C,
                        sensorFps=CAMERA_FPS,
                    )

                    # Get camera outputs (encoder-friendly formats)
                    rgb_out = cam_rgb.requestOutput(RESOLUTION, type=dai.ImgFrame.Type.NV12)
                    left_out = cam_left.requestOutput(RESOLUTION, type=dai.ImgFrame.Type.GRAY8)
                    right_out = cam_right.requestOutput(RESOLUTION, type=dai.ImgFrame.Type.GRAY8)

                    # StereoDepth (on-device depth/disparity from mono pair)
                    stereo = pipeline.create(dai.node.StereoDepth)
                    left_out.link(stereo.left)
                    right_out.link(stereo.right)
                    stereo.setRectification(True)
                    stereo.setLeftRightCheck(True)
                    stereo.setDepthAlign(dai.CameraBoardSocket.CAM_A)

                    # H.265 video encoder (encode on camera, not Pi)
                    enc_rgb = pipeline.create(dai.node.VideoEncoder)
                    enc_rgb.setDefaultProfilePreset(CAMERA_FPS, dai.VideoEncoderProperties.Profile.H265_MAIN)
                    enc_rgb.setBitrate(H265_BITRATE)
                    rgb_out.link(enc_rgb.input)

                    # Sync node - synchronizes RGB + depth by timestamp
                    sync = pipeline.create(dai.node.Sync)
                    sync.setSyncThreshold(timedelta(milliseconds=SYNC_THRESHOLD_MS))
                    enc_rgb.out.link(sync.inputs["rgb"])
                    stereo.depth.link(sync.inputs["depth"])

                    # IMU (separate - runs at higher rate)
                    imu = pipeline.create(dai.node.IMU)
                    imu.enableIMUSensor(dai.IMUSensor.ACCELEROMETER_RAW, IMU_HZ)
                    imu.enableIMUSensor(dai.IMUSensor.GYROSCOPE_RAW, IMU_HZ)
                    imu.setBatchReportThreshold(1)
                    imu.setMaxBatchReports(10)

                    # Output queues - synchronized RGB + depth + IMU
                    q_sync = sync.out.createOutputQueue(maxSize=2, blocking=True)
                    q_imu = imu.out.createOutputQueue(maxSize=100, blocking=False)

                    log.info(
                        f"Pipeline: {RESOLUTION[0]}x{RESOLUTION[1]} @ {CAMERA_FPS}fps, "
                        f"H.265 @ {H265_BITRATE//1_000_000}Mbps, RGB + depth aligned, "
                        f"sync threshold {SYNC_THRESHOLD_MS}ms"
                    )

                    # Start pipeline
                    pipeline.start()

                    # Ensure base recordings directory exists
                    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

                    # Ready - immediately start recording
                    self._state = State.READY
                    log.info("Device ready, starting recording automatically")
                    self._start_recording()

                    # Main loop - record continuously until shutdown
                    last_fsync = time.monotonic()
                    while self._running and pipeline.isRunning():
                        if self._state != State.RECORDING or not self._recorder:
                            time.sleep(0.05)
                            continue

                        imu_packets = q_imu.tryGetAll()
                        if imu_packets:
                            for imu_data in imu_packets:
                                self._recorder.write_imu(imu_data)

                        sync_msgs = self._drain_queue(q_sync, "sync")
                        if sync_msgs:
                            for sync_msg in sync_msgs:
                                for name, frame in sync_msg:
                                    ts = int(frame.getTimestampDevice().total_seconds() * 1e9)
                                    data = frame.getData()
                                    if name == "depth":
                                        data = lz4f.compress(data)
                                    self._recorder.write_frame(name, data, ts)
                        if not sync_msgs and not imu_packets:
                            time.sleep(0.005)
                            continue

                        # Periodic fsync to survive hard power cuts
                        now = time.monotonic()
                        if now - last_fsync >= FSYNC_INTERVAL_S:
                            self._recorder.flush()
                            last_fsync = now

                        # Periodic disk space check
                        if now - self._last_disk_check >= DISK_CHECK_INTERVAL_S:
                            self._last_disk_check = now
                            if not self._check_disk_space():
                                log.warning("Stopping recording due to low disk space")
                                self._stop_recording()
                                continue

                        # Rotate recording for resilience
                        if (
                            self._segment_start_monotonic is not None
                            and now - self._segment_start_monotonic >= SEGMENT_MINUTES * 60
                        ):
                            log.info("Rotating recording segment")
                            self._stop_recording()
                            self._start_recording()

            except Exception as e:
                log.exception(f"Application error: {e}")

            finally:
                log.info("Cleaning up...")
                # Stop recording if active
                if self._recorder:
                    self._recorder.close()
                    self._recorder = None
                self._segment_start_monotonic = None
                if device is not None:
                    try:
                        device.close()
                    except Exception:
                        pass
                log.info("Cleanup complete")

            if self._running:
                log.info(f"Retrying device init in {DEVICE_RETRY_INTERVAL_S:.1f}s...")
                time.sleep(DEVICE_RETRY_INTERVAL_S)


def main() -> None:
    """Entry point."""
    log.info("Starting OAK-D Capture...")
    app = CaptureApp()
    app.run()


if __name__ == "__main__":
    main()
