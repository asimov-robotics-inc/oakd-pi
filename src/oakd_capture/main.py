"""Main application: camera pipeline, recording, and state machine using depthai v3."""

import base64
import signal
import logging
import json
import time
from enum import Enum, auto
from pathlib import Path
from datetime import datetime
from typing import Optional

import cv2
import numpy as np
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


class State(Enum):
    INITIALIZING = auto()
    READY = auto()
    RECORDING = auto()
    SHUTTING_DOWN = auto()


class McapRecorder:
    """MCAP file recorder with Foxglove-compatible schemas."""

    # Foxglove CompressedImage JSON schema
    COMPRESSED_IMAGE_SCHEMA = json.dumps({
        "type": "object",
        "properties": {
            "timestamp": {"type": "object", "properties": {"sec": {"type": "integer"}, "nsec": {"type": "integer"}}},
            "frame_id": {"type": "string"},
            "data": {"type": "string", "contentEncoding": "base64"},
            "format": {"type": "string"},
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
        self._schemas["image"] = self._writer.register_schema(
            name="foxglove.CompressedImage",
            encoding="jsonschema",
            data=self.COMPRESSED_IMAGE_SCHEMA.encode(),
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
            schema_id=self._schemas["image"],
        )
        self._channels["left"] = self._writer.register_channel(
            topic="/oak/left",
            message_encoding="json",
            schema_id=self._schemas["image"],
        )
        self._channels["right"] = self._writer.register_channel(
            topic="/oak/right",
            message_encoding="json",
            schema_id=self._schemas["image"],
        )
        self._channels["imu"] = self._writer.register_channel(
            topic="/oak/imu",
            message_encoding="json",
            schema_id=self._schemas["imu"],
        )
        log.info(f"Opened MCAP: {self._filepath}")

    def write_frame(self, channel_name: str, frame: dai.ImgFrame, timestamp_ns: int):
        """Write a frame to the MCAP file as JPEG."""
        if not self._writer or not self._file or channel_name not in self._channels:
            return

        # Get frame as numpy array and encode as JPEG
        img = frame.getCvFrame()
        _, jpeg_data = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])

        # Create Foxglove CompressedImage message
        sec = timestamp_ns // 1_000_000_000
        nsec = timestamp_ns % 1_000_000_000
        msg = {
            "timestamp": {"sec": sec, "nsec": nsec},
            "frame_id": channel_name,
            "data": base64.b64encode(jpeg_data.tobytes()).decode("ascii"),
            "format": "jpeg",
        }

        self._writer.add_message(
            channel_id=self._channels[channel_name],
            log_time=timestamp_ns,
            publish_time=timestamp_ns,
            data=json.dumps(msg).encode(),
        )

    def write_imu(self, imu_data: dai.IMUData, timestamp_ns: int):
        """Write IMU data to the MCAP file."""
        if not self._writer or not self._file:
            return

        for packet in imu_data.packets:
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
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
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
                "session_start": datetime.now().isoformat(),
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
        self._recording_count += 1
        mcap_path = self._session_dir / f"recording_{self._recording_count:03d}.mcap"

        self._recorder = McapRecorder(mcap_path)
        self._recorder.open()

        log.info(f"Recording {self._recording_count} started: {mcap_path}")
        self._state = State.RECORDING
        self._hw.buzzer.start()

    def _stop_recording(self) -> None:
        """Stop current recording."""
        # Change state FIRST to prevent race condition with main loop
        self._state = State.READY

        if self._recorder:
            self._recorder.close()
            self._recorder = None

        log.info("Recording stopped")
        self._hw.buzzer.stop()

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
            device_id = device.getMxId()  # Get ID before pipeline starts

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

                # IMU
                imu = pipeline.create(dai.node.IMU)
                imu.enableIMUSensor(dai.IMUSensor.ACCELEROMETER_RAW, 100)
                imu.enableIMUSensor(dai.IMUSensor.GYROSCOPE_RAW, 100)
                imu.setBatchReportThreshold(1)
                imu.setMaxBatchReports(10)

                # Create output queues
                q_rgb = rgb_out.createOutputQueue(maxSize=4, blocking=False)
                q_left = left_out.createOutputQueue(maxSize=4, blocking=False)
                q_right = right_out.createOutputQueue(maxSize=4, blocking=False)
                q_imu = imu.out.createOutputQueue(maxSize=50, blocking=False)

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
                        self._stop_recording()

                    # Get frames from queues
                    rgb_frame = q_rgb.tryGet()
                    left_frame = q_left.tryGet()
                    right_frame = q_right.tryGet()
                    imu_data = q_imu.tryGet()

                    # Record if in recording state
                    if self._state == State.RECORDING and self._recorder:
                        now_ns = time.time_ns()

                        if rgb_frame:
                            self._recorder.write_frame("rgb", rgb_frame, now_ns)
                        if left_frame:
                            self._recorder.write_frame("left", left_frame, now_ns)
                        if right_frame:
                            self._recorder.write_frame("right", right_frame, now_ns)
                        if imu_data:
                            self._recorder.write_imu(imu_data, now_ns)

                    # Small sleep to prevent busy loop
                    time.sleep(0.001)

        except Exception as e:
            log.exception(f"Application error: {e}")
            if hw:
                try:
                    hw.buzzer.error()
                except:
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
