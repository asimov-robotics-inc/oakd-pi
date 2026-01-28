"""Main application: camera pipeline, recording, and state machine using depthai v3."""

import base64
import signal
import logging
import json
import time
import shutil
from enum import Enum, auto
from pathlib import Path
from datetime import datetime
from typing import Optional

import depthai as dai
from mcap.writer import Writer

from oakd_capture.hardware import Hardware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
log = logging.getLogger(__name__)

# Configuration
RECORDINGS_DIR = Path.home() / "recordings"
RGB_FPS = 30
MONO_FPS = 30
IR_INTENSITY = 0.5
QUEUE_TIMEOUT_S = 0.5
STOP_DRAIN_S = 0.5
MIN_FREE_GB = 2.0
H264_BITRATE_KBPS = 8000
USE_SYNC = True


class State(Enum):
    INITIALIZING = auto()
    READY = auto()
    RECORDING = auto()
    SHUTTING_DOWN = auto()


class McapRecorder:
    """MCAP file recorder for encoded video + IMU."""

    # Encoded video JSON schema (codec + base64 payload)
    ENCODED_VIDEO_SCHEMA = json.dumps({
        "type": "object",
        "properties": {
            "timestamp": {"type": "object", "properties": {"sec": {"type": "integer"}, "nsec": {"type": "integer"}}},
            "frame_id": {"type": "string"},
            "data": {"type": "string", "contentEncoding": "base64"},
            "codec": {"type": "string"},
        },
    })

    # IMU JSON schema
    IMU_SCHEMA = json.dumps({
        "type": "object",
        "properties": {
            "timestamp": {"type": "object", "properties": {"sec": {"type": "integer"}, "nsec": {"type": "integer"}}},
            "linear_acceleration": {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}, "z": {"type": "number"}}},
            "angular_velocity": {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}, "z": {"type": "number"}}},
        },
    })

    def __init__(self, filepath: Path):
        self._filepath = filepath
        self._file = None
        self._writer = None
        self._channels = {}
        self._schemas = {}

    def open(self):
        """Open MCAP file for writing."""
        self._file = open(self._filepath, "wb")
        self._writer = Writer(self._file)
        self._writer.start()

        # Register schemas
        self._schemas["video"] = self._writer.register_schema(
            name="oakd.EncodedVideo",
            encoding="jsonschema",
            data=self.ENCODED_VIDEO_SCHEMA.encode(),
        )
        self._schemas["imu"] = self._writer.register_schema(
            name="foxglove.Imu",
            encoding="jsonschema",
            data=self.IMU_SCHEMA.encode(),
        )

        # Register channels with schemas
        self._channels["rgb"] = self._writer.register_channel(
            topic="/oak/rgb",
            message_encoding="json",
            schema_id=self._schemas["video"],
        )
        self._channels["left"] = self._writer.register_channel(
            topic="/oak/left",
            message_encoding="json",
            schema_id=self._schemas["video"],
        )
        self._channels["right"] = self._writer.register_channel(
            topic="/oak/right",
            message_encoding="json",
            schema_id=self._schemas["video"],
        )
        self._channels["imu"] = self._writer.register_channel(
            topic="/oak/imu",
            message_encoding="json",
            schema_id=self._schemas["imu"],
        )
        log.info(f"Opened MCAP: {self._filepath}")

    def write_encoded_frame(self, channel_name: str, frame: dai.ImgFrame, timestamp_ns: int, codec: str):
        """Write an encoded frame to the MCAP file."""
        if not self._writer or not self._file or channel_name not in self._channels:
            return

        payload = bytes(frame.getData())
        if not payload:
            log.warning("Empty encoded frame payload; skipping")
            return

        sec = timestamp_ns // 1_000_000_000
        nsec = timestamp_ns % 1_000_000_000
        msg = {
            "timestamp": {"sec": sec, "nsec": nsec},
            "frame_id": channel_name,
            "data": base64.b64encode(payload).decode("ascii"),
            "codec": codec,
        }

        self._writer.add_message(
            channel_id=self._channels[channel_name],
            log_time=timestamp_ns,
            publish_time=timestamp_ns,
            data=json.dumps(msg).encode(),
        )

    def write_imu(self, imu_data: dai.IMUData):
        """Write IMU data to the MCAP file."""
        if not self._writer or not self._file:
            return

        for packet in imu_data.packets:
            timestamp_ns = int(packet.acceleroMeter.getTimestampDevice().total_seconds() * 1e9)
            sec = timestamp_ns // 1_000_000_000
            nsec = timestamp_ns % 1_000_000_000
            msg = {
                "timestamp": {"sec": sec, "nsec": nsec},
                "linear_acceleration": {
                    "x": packet.acceleroMeter.x,
                    "y": packet.acceleroMeter.y,
                    "z": packet.acceleroMeter.z,
                },
                "angular_velocity": {
                    "x": packet.gyroscope.x,
                    "y": packet.gyroscope.y,
                    "z": packet.gyroscope.z,
                },
            }
            self._writer.add_message(
                channel_id=self._channels["imu"],
                log_time=timestamp_ns,
                publish_time=timestamp_ns,
                data=json.dumps(msg).encode(),
            )

    def close(self):
        """Close the MCAP file."""
        if self._writer:
            self._writer.finish()
            self._writer = None
        if self._file:
            self._file.close()
            self._file = None
        log.info(f"Closed MCAP: {self._filepath}")


class CaptureApp:
    """Main application orchestrating hardware, camera, and recording."""

    def __init__(self):
        self._state = State.INITIALIZING
        self._running = True
        self._session_dir: Optional[Path] = None
        self._recording_count = 0
        self._hw: Optional[Hardware] = None
        self._recorder: Optional[McapRecorder] = None
        self._stop_requested = False  # Thread-safe flag for stop request
        self._session_start: Optional[datetime] = None
        self._last_queue_warn = {}

        # Register signal handlers
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signals."""
        log.info(f"Received signal {signum}, shutting down...")
        self._running = False
        self._state = State.SHUTTING_DOWN

    def _create_session(self) -> Path:
        """Create a new recording session directory."""
        self._session_start = datetime.now()
        timestamp = self._session_start.strftime("%Y%m%d_%H%M%S")
        session_dir = RECORDINGS_DIR / f"session_{timestamp}"
        session_dir.mkdir(parents=True, exist_ok=True)
        log.info(f"Created session: {session_dir}")
        return session_dir

    def _save_calibration(self, device: dai.Device) -> None:
        """Save camera calibration data."""
        if not self._session_dir:
            return
        try:
            calib = device.readCalibration()
            calib_path = self._session_dir / "calibration.json"
            calib.eepromToJsonFile(str(calib_path))
            log.info(f"Saved calibration to {calib_path}")
        except Exception as e:
            log.warning(f"Failed to save calibration: {e}")

    def _save_metadata(self) -> None:
        """Save session metadata."""
        if not self._session_dir:
            return
        try:
            metadata = {
                "session_start": self._session_start.isoformat() if self._session_start else datetime.now().isoformat(),
                "recordings": self._recording_count,
            }
            metadata_path = self._session_dir / "metadata.json"
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2)
            log.info(f"Saved metadata to {metadata_path}")
        except Exception as e:
            log.warning(f"Failed to save metadata: {e}")

    def _on_button_press(self) -> None:
        """Handle button press based on current state.

        Note: This runs in a gpiozero callback thread, so we use a flag
        to signal the main loop to stop recording (thread-safe).
        """
        if self._state == State.READY:
            self._start_recording()
        elif self._state == State.RECORDING:
            # Signal main loop to stop - don't close recorder from callback thread
            self._stop_requested = True

    def _start_recording(self) -> None:
        """Start a new recording."""
        if not self._session_dir:
            log.warning("No session directory available; cannot start recording")
            return

        try:
            free_gb = shutil.disk_usage(self._session_dir).free / (1024**3)
            if free_gb < MIN_FREE_GB:
                log.warning(f"Low disk space ({free_gb:.2f} GB free); refusing to start recording")
                self._hw.buzzer.error()
                return
        except Exception as e:
            log.warning(f"Disk space check failed: {e}")

        self._recording_count += 1
        mcap_path = self._session_dir / f"recording_{self._recording_count:03d}.mcap"

        self._recorder = McapRecorder(mcap_path)
        self._recorder.open()

        log.info(f"Recording {self._recording_count} started: {mcap_path}")
        self._state = State.RECORDING
        self._hw.buzzer.beep_async(1)

    def _stop_recording(self) -> None:
        """Stop current recording."""
        # Change state FIRST to prevent race condition with main loop
        self._state = State.READY

        if self._recorder:
            self._recorder.close()
            self._recorder = None

        log.info("Recording stopped")
        self._hw.buzzer.beep_async(2)

    def _get_with_timeout(self, queue, timeout_s: float, name: str):
        """Get a queue item with a timeout; log warnings if no data arrives."""
        item = None
        try:
            item = queue.get(timeout=timeout_s)
        except (TypeError, AttributeError):
            end = time.monotonic() + timeout_s
            while self._running and time.monotonic() < end:
                item = queue.tryGet()
                if item is not None:
                    break
                time.sleep(0.001)

        if item is None:
            now = time.monotonic()
            last = self._last_queue_warn.get(name, 0.0)
            if now - last > 5.0:
                log.warning(f"No data from {name} queue for {timeout_s:.1f}s")
                self._last_queue_warn[name] = now
        return item

    def _get_all_with_timeout(self, queue, timeout_s: float, name: str):
        """Get all queued items with a timeout; log warnings if no data arrives."""
        items = []
        try:
            items = queue.getAll(timeout=timeout_s)
        except (TypeError, AttributeError):
            end = time.monotonic() + timeout_s
            while self._running and time.monotonic() < end:
                try:
                    items = queue.tryGetAll()
                except AttributeError:
                    item = queue.tryGet()
                    items = [item] if item is not None else []
                if items:
                    break
                time.sleep(0.001)

        if not items:
            now = time.monotonic()
            last = self._last_queue_warn.get(name, 0.0)
            if now - last > 5.0:
                log.warning(f"No data from {name} queue for {timeout_s:.1f}s")
                self._last_queue_warn[name] = now
        return items

    def _extract_sync(self, msg_group):
        """Extract frames from a sync message group."""
        rgb_frame = None
        left_frame = None
        right_frame = None
        imu_data = None
        try:
            rgb_frame = msg_group["rgb"]
            left_frame = msg_group["left"]
            right_frame = msg_group["right"]
            imu_data = msg_group["imu"]
        except Exception:
            get = getattr(msg_group, "get", None)
            if callable(get):
                rgb_frame = get("rgb")
                left_frame = get("left")
                right_frame = get("right")
                imu_data = get("imu")
        return rgb_frame, left_frame, right_frame, imu_data

    def _write_frames(self, rgb_frame, left_frame, right_frame, imu_packets):
        """Write any available frames/imu to the recorder."""
        if rgb_frame:
            ts = int(rgb_frame.getTimestampDevice().total_seconds() * 1e9)
            self._recorder.write_encoded_frame("rgb", rgb_frame, ts, "h264")
        if left_frame:
            ts = int(left_frame.getTimestampDevice().total_seconds() * 1e9)
            self._recorder.write_encoded_frame("left", left_frame, ts, "h264")
        if right_frame:
            ts = int(right_frame.getTimestampDevice().total_seconds() * 1e9)
            self._recorder.write_encoded_frame("right", right_frame, ts, "h264")
        if imu_packets:
            for imu_data in imu_packets:
                self._recorder.write_imu(imu_data)

    def _drain_and_stop_recording(self, q_sync=None, q_rgb=None, q_left=None, q_right=None, q_imu=None, use_sync=False):
        """Drain remaining queued data briefly before stopping."""
        if not self._recorder:
            self._stop_recording()
            return

        end = time.monotonic() + STOP_DRAIN_S
        while self._running and time.monotonic() < end:
            if use_sync and q_sync:
                msg_group = q_sync.tryGet()
                if not msg_group:
                    break
                rgb_frame, left_frame, right_frame, imu_data = self._extract_sync(msg_group)
                imu_packets = [imu_data] if imu_data else []
                self._write_frames(rgb_frame, left_frame, right_frame, imu_packets)
            else:
                rgb_frame = q_rgb.tryGet() if q_rgb else None
                left_frame = q_left.tryGet() if q_left else None
                right_frame = q_right.tryGet() if q_right else None
                if q_imu:
                    try:
                        imu_packets = q_imu.tryGetAll()
                    except AttributeError:
                        imu_item = q_imu.tryGet()
                        imu_packets = [imu_item] if imu_item is not None else []
                else:
                    imu_packets = []
                if not (rgb_frame or left_frame or right_frame or imu_packets):
                    break
                self._write_frames(rgb_frame, left_frame, right_frame, imu_packets)

        self._stop_recording()

    def run(self) -> None:
        """Main application loop."""
        hw = None
        device = None

        try:
            hw = Hardware()
            self._hw = hw

            log.info("Initializing camera...")

            # Connect to device first to enable IR
            device = dai.Device()

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
                    sensorFps=RGB_FPS,
                )

                # Mono cameras for stereo
                cam_left = pipeline.create(dai.node.Camera).build(
                    boardSocket=dai.CameraBoardSocket.CAM_B,
                    sensorFps=MONO_FPS,
                )

                cam_right = pipeline.create(dai.node.Camera).build(
                    boardSocket=dai.CameraBoardSocket.CAM_C,
                    sensorFps=MONO_FPS,
                )

                # Get camera outputs
                rgb_out = cam_rgb.requestOutput((640, 360))
                left_out = cam_left.requestOutput((640, 400))
                right_out = cam_right.requestOutput((640, 400))

                # Video encoders (H.264 on-device)
                enc_rgb = pipeline.create(dai.node.VideoEncoder)
                enc_left = pipeline.create(dai.node.VideoEncoder)
                enc_right = pipeline.create(dai.node.VideoEncoder)
                enc_rgb.setDefaultProfilePreset(RGB_FPS, dai.VideoEncoderProperties.Profile.H264_MAIN)
                enc_left.setDefaultProfilePreset(MONO_FPS, dai.VideoEncoderProperties.Profile.H264_MAIN)
                enc_right.setDefaultProfilePreset(MONO_FPS, dai.VideoEncoderProperties.Profile.H264_MAIN)
                for enc in (enc_rgb, enc_left, enc_right):
                    try:
                        enc.setBitrateKbps(H264_BITRATE_KBPS)
                    except Exception:
                        pass

                rgb_out.link(enc_rgb.input)
                left_out.link(enc_left.input)
                right_out.link(enc_right.input)

                # IMU
                imu = pipeline.create(dai.node.IMU)
                imu.enableIMUSensor(dai.IMUSensor.ACCELEROMETER_RAW, 100)
                imu.enableIMUSensor(dai.IMUSensor.GYROSCOPE_RAW, 100)
                imu.setBatchReportThreshold(1)
                imu.setMaxBatchReports(10)

                # Create output queues (blocking with timeout warnings)
                q_sync = None
                use_sync = False
                if USE_SYNC:
                    try:
                        sync = pipeline.create(dai.node.Sync)
                        enc_rgb.bitstream.link(sync.inputs["rgb"])
                        enc_left.bitstream.link(sync.inputs["left"])
                        enc_right.bitstream.link(sync.inputs["right"])
                        imu.out.link(sync.inputs["imu"])
                        q_sync = sync.out.createOutputQueue(maxSize=30, blocking=True)
                        use_sync = True
                        log.info("Sync enabled for RGB/left/right/IMU")
                    except Exception as e:
                        log.warning(f"Sync not available; falling back to separate queues: {e}")

                q_rgb = None
                q_left = None
                q_right = None
                q_imu = None
                if not use_sync:
                    q_rgb = enc_rgb.bitstream.createOutputQueue(maxSize=60, blocking=True)
                    q_left = enc_left.bitstream.createOutputQueue(maxSize=60, blocking=True)
                    q_right = enc_right.bitstream.createOutputQueue(maxSize=60, blocking=True)
                    q_imu = imu.out.createOutputQueue(maxSize=200, blocking=True)

                # Start pipeline
                pipeline.start()

                # Create session and save calibration
                self._session_dir = self._create_session()
                self._save_calibration(device)

                # Ready state
                self._state = State.READY
                log.info("Device ready")
                hw.buzzer.ready()

                # Register button callback
                hw.button.set_callback(self._on_button_press)

                # Main loop
                while self._running and pipeline.isRunning():
                    # Check for stop request from button callback (thread-safe)
                    if self._stop_requested:
                        self._stop_requested = False
                        self._drain_and_stop_recording(
                            q_sync=q_sync,
                            q_rgb=q_rgb,
                            q_left=q_left,
                            q_right=q_right,
                            q_imu=q_imu,
                            use_sync=use_sync,
                        )

                    if self._state != State.RECORDING or not self._recorder:
                        time.sleep(0.05)
                        continue

                    if use_sync and q_sync:
                        msg_group = self._get_with_timeout(q_sync, QUEUE_TIMEOUT_S, "sync")
                        if msg_group:
                            rgb_frame, left_frame, right_frame, imu_data = self._extract_sync(msg_group)
                            imu_packets = [imu_data] if imu_data else []
                            self._write_frames(rgb_frame, left_frame, right_frame, imu_packets)
                    else:
                        # Get frames from queues with timeout
                        rgb_frame = self._get_with_timeout(q_rgb, QUEUE_TIMEOUT_S, "rgb")
                        left_frame = self._get_with_timeout(q_left, QUEUE_TIMEOUT_S, "left")
                        right_frame = self._get_with_timeout(q_right, QUEUE_TIMEOUT_S, "right")
                        imu_packets = self._get_all_with_timeout(q_imu, QUEUE_TIMEOUT_S, "imu")
                        self._write_frames(rgb_frame, left_frame, right_frame, imu_packets)

        except Exception as e:
            log.exception(f"Application error: {e}")
            if hw:
                try:
                    hw.buzzer.error()
                except Exception:
                    pass

        finally:
            log.info("Cleaning up...")
            # Stop recording if active
            if self._recorder:
                self._recorder.close()
                self._recorder = None
            # Save metadata
            if self._session_dir:
                self._save_metadata()
            # Cleanup hardware
            if hw:
                hw.cleanup()
            log.info("Cleanup complete")


def main() -> None:
    """Entry point."""
    log.info("Starting OAK-D Capture...")
    app = CaptureApp()
    app.run()


if __name__ == "__main__":
    main()
