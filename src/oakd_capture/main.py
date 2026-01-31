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
from datetime import datetime, timezone
from typing import Optional

import depthai as dai
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
RESOLUTION = (1280, 720)  # 720p for all cameras
H265_BITRATE = 10_000_000  # 10 Mbps - high quality for 720p

# Synchronization settings
SEQ_SYNC_MAX_BUFFER = 120  # Max buffered frames per stream for sequence matching
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
        for topic_name in ("rgb", "left", "right", "imu"):
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
                "sync_method": "sequence_number",
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
        self._seq_warned = False

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
                    "sync_method": "sequence_number",
                    "ir_intensity": IR_INTENSITY,
                    "video_encoding": "h265",
                    "h265_bitrate": H265_BITRATE,
                    "stereo": {
                        "left_right_check": False,
                        "rectification": False,
                        "encoding": "h265",
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
        self._rgb_buf = {}
        self._left_buf = {}
        self._right_buf = {}
        self._seq_warned = False

    def _stop_recording(self) -> None:
        """Stop current recording."""
        self._state = State.READY
        self._segment_start_monotonic = None
        self._rgb_buf = {}
        self._left_buf = {}
        self._right_buf = {}
        self._seq_warned = False

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

                    # Convert mono frames to NV12 for H.265 encoder
                    manip_left = pipeline.create(dai.node.ImageManip)
                    manip_left.initialConfig.setOutputSize(RESOLUTION[0], RESOLUTION[1])
                    manip_left.initialConfig.setFrameType(dai.ImgFrame.Type.NV12)
                    manip_left.setMaxOutputFrameSize(int(RESOLUTION[0] * RESOLUTION[1] * 3 / 2))
                    left_out.link(manip_left.inputImage)

                    manip_right = pipeline.create(dai.node.ImageManip)
                    manip_right.initialConfig.setOutputSize(RESOLUTION[0], RESOLUTION[1])
                    manip_right.initialConfig.setFrameType(dai.ImgFrame.Type.NV12)
                    manip_right.setMaxOutputFrameSize(int(RESOLUTION[0] * RESOLUTION[1] * 3 / 2))
                    right_out.link(manip_right.inputImage)

                    # H.265 video encoder (encode on camera, not Pi)
                    enc_rgb = pipeline.create(dai.node.VideoEncoder)
                    enc_rgb.setDefaultProfilePreset(CAMERA_FPS, dai.VideoEncoderProperties.Profile.H265_MAIN)
                    enc_rgb.setBitrate(H265_BITRATE)
                    rgb_out.link(enc_rgb.input)

                    enc_left = pipeline.create(dai.node.VideoEncoder)
                    enc_left.setDefaultProfilePreset(CAMERA_FPS, dai.VideoEncoderProperties.Profile.H265_MAIN)
                    enc_left.setBitrate(H265_BITRATE)
                    manip_left.out.link(enc_left.input)

                    enc_right = pipeline.create(dai.node.VideoEncoder)
                    enc_right.setDefaultProfilePreset(CAMERA_FPS, dai.VideoEncoderProperties.Profile.H265_MAIN)
                    enc_right.setBitrate(H265_BITRATE)
                    manip_right.out.link(enc_right.input)

                    # IMU (separate - runs at higher rate)
                    imu = pipeline.create(dai.node.IMU)
                    imu.enableIMUSensor(dai.IMUSensor.ACCELEROMETER_RAW, IMU_HZ)
                    imu.enableIMUSensor(dai.IMUSensor.GYROSCOPE_RAW, IMU_HZ)
                    imu.setBatchReportThreshold(1)
                    imu.setMaxBatchReports(10)

                    # Output queues - encoded streams + IMU
                    q_rgb = enc_rgb.out.createOutputQueue(maxSize=8, blocking=False)
                    q_left = enc_left.out.createOutputQueue(maxSize=8, blocking=False)
                    q_right = enc_right.out.createOutputQueue(maxSize=8, blocking=False)
                    q_imu = imu.out.createOutputQueue(maxSize=100, blocking=False)

                    log.info(
                        f"Pipeline: {RESOLUTION[0]}x{RESOLUTION[1]} @ {CAMERA_FPS}fps, "
                        f"H.265 @ {H265_BITRATE//1_000_000}Mbps, stereo L/R + RGB, "
                        f"sync by sequence number"
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

                        rgb_packets = self._drain_queue(q_rgb, "rgb")
                        left_packets = self._drain_queue(q_left, "left")
                        right_packets = self._drain_queue(q_right, "right")

                        if not rgb_packets and not left_packets and not right_packets and not imu_packets:
                            time.sleep(0.005)
                            continue

                        for pkt in rgb_packets:
                            self._rgb_buf[pkt.getSequenceNum()] = pkt
                        for pkt in left_packets:
                            self._left_buf[pkt.getSequenceNum()] = pkt
                        for pkt in right_packets:
                            self._right_buf[pkt.getSequenceNum()] = pkt

                        # Trim buffers to prevent unbounded growth
                        for buf in (self._rgb_buf, self._left_buf, self._right_buf):
                            if len(buf) > SEQ_SYNC_MAX_BUFFER:
                                oldest_seq = min(buf.keys())
                                buf.pop(oldest_seq, None)
                                if not self._seq_warned:
                                    log.warning("Sequence sync buffer overflow; dropping oldest frames")
                                    self._seq_warned = True

                        # Write any complete triplets by sequence number
                        while True:
                            common = set(self._rgb_buf) & set(self._left_buf) & set(self._right_buf)
                            if not common:
                                break
                            seq = min(common)
                            rgb_pkt = self._rgb_buf.pop(seq)
                            left_pkt = self._left_buf.pop(seq)
                            right_pkt = self._right_buf.pop(seq)

                            ts_rgb = int(rgb_pkt.getTimestampDevice().total_seconds() * 1e9)
                            ts_left = int(left_pkt.getTimestampDevice().total_seconds() * 1e9)
                            ts_right = int(right_pkt.getTimestampDevice().total_seconds() * 1e9)

                            self._recorder.write_frame("rgb", rgb_pkt.getData(), ts_rgb)
                            self._recorder.write_frame("left", left_pkt.getData(), ts_left)
                            self._recorder.write_frame("right", right_pkt.getData(), ts_right)

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
