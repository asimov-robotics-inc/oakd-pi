"""MCAP recording viewer — streams RGB, depth colormap, and IMU traces."""

import argparse
import struct
import sys
import time
from collections import deque
from pathlib import Path

import av
import cv2
import numpy as np
from mcap.reader import make_reader


# Layout constants
VIDEO_W, VIDEO_H = 1280, 720
IMU_PLOT_H = 240
CANVAS_W = VIDEO_W * 2

# IMU plot settings
IMU_BUF_LEN = 400  # ~2s at 200Hz
ACCEL_RANGE = 20.0  # m/s^2
GYRO_RANGE = 10.0   # rad/s
ACCEL_COLORS = [(0, 0, 255), (0, 200, 0), (255, 100, 0)]   # R,G,B for x,y,z
GYRO_COLORS = [(180, 0, 255), (0, 220, 220), (255, 180, 0)]

DEPTH_MAX_MM = 10_000  # clip depth at 10m


def make_h265_decoder():
    """Create a PyAV H.265 codec context for decoding raw NAL units."""
    return av.CodecContext.create("hevc", "r")


def decode_h265(decoder, data: bytes) -> np.ndarray | None:
    """Decode a raw H.265 frame blob to a BGR numpy array."""
    packet = av.Packet(data)
    try:
        frames = decoder.decode(packet)
    except av.error.InvalidDataError:
        return None
    for frame in frames:
        return frame.to_ndarray(format="bgr24")
    return None


def depth_to_color(data: bytes) -> np.ndarray:
    """Convert raw uint16 depth buffer to a TURBO colormap image."""
    arr = np.frombuffer(data, dtype=np.uint16).reshape(VIDEO_H, VIDEO_W)
    clipped = np.clip(arr, 0, DEPTH_MAX_MM).astype(np.float32)
    norm = (clipped * (255.0 / DEPTH_MAX_MM)).astype(np.uint8)
    return cv2.applyColorMap(norm, cv2.COLORMAP_TURBO)


def unpack_imu(data: bytes):
    """Unpack 48-byte IMU sample: ax,ay,az,gx,gy,gz."""
    return struct.unpack("<6d", data)


def draw_imu_plot(accel_buf, gyro_buf) -> np.ndarray:
    """Draw a scrolling IMU plot on a black canvas using cv2.line."""
    canvas = np.zeros((IMU_PLOT_H, CANVAS_W, 3), dtype=np.uint8)
    half_w = CANVAS_W // 2
    mid_y = IMU_PLOT_H // 2

    # Draw center lines
    cv2.line(canvas, (0, mid_y), (half_w, mid_y), (40, 40, 40), 1)
    cv2.line(canvas, (half_w, mid_y), (CANVAS_W, mid_y), (40, 40, 40), 1)

    # Labels
    cv2.putText(canvas, "Accel (m/s2)", (10, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)
    cv2.putText(canvas, "Gyro (rad/s)", (half_w + 10, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)

    n = len(accel_buf)
    if n < 2:
        return canvas

    x_step = half_w / max(n - 1, 1)

    for axis in range(3):
        # Accel trace
        for i in range(1, n):
            x0 = int((i - 1) * x_step)
            x1 = int(i * x_step)
            y0 = mid_y - int(accel_buf[i - 1][axis] / ACCEL_RANGE * mid_y)
            y1 = mid_y - int(accel_buf[i][axis] / ACCEL_RANGE * mid_y)
            y0 = max(0, min(IMU_PLOT_H - 1, y0))
            y1 = max(0, min(IMU_PLOT_H - 1, y1))
            cv2.line(canvas, (x0, y0), (x1, y1), ACCEL_COLORS[axis], 1, cv2.LINE_AA)

        # Gyro trace
        for i in range(1, n):
            x0 = half_w + int((i - 1) * x_step)
            x1 = half_w + int(i * x_step)
            y0 = mid_y - int(gyro_buf[i - 1][axis] / GYRO_RANGE * mid_y)
            y1 = mid_y - int(gyro_buf[i][axis] / GYRO_RANGE * mid_y)
            y0 = max(0, min(IMU_PLOT_H - 1, y0))
            y1 = max(0, min(IMU_PLOT_H - 1, y1))
            cv2.line(canvas, (x0, y0), (x1, y1), GYRO_COLORS[axis], 1, cv2.LINE_AA)

    # Axis legends
    labels = ["X", "Y", "Z"]
    for i, (lbl, col) in enumerate(zip(labels, ACCEL_COLORS)):
        cv2.putText(canvas, lbl, (half_w - 60 + i * 25, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.4, col, 1)
    for i, (lbl, col) in enumerate(zip(labels, GYRO_COLORS)):
        cv2.putText(canvas, lbl, (CANVAS_W - 60 + i * 25, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.4, col, 1)

    return canvas


def stream_mcap(path: str):
    """Yield (topic, log_time, data) tuples in timestamp order from an MCAP file."""
    with open(path, "rb") as f:
        reader = make_reader(f)
        for _schema, channel, message in reader.iter_messages():
            yield channel.topic, message.log_time, message.data


def main():
    parser = argparse.ArgumentParser(description="Play back an MCAP recording with RGB, depth, and IMU.")
    parser.add_argument("mcap", help="Path to the .mcap file")
    args = parser.parse_args()

    mcap_path = Path(args.mcap)
    if not mcap_path.exists():
        print(f"File not found: {mcap_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Streaming {mcap_path} ...")

    decoder = make_h265_decoder()

    # IMU rolling buffers
    accel_buf = deque(maxlen=IMU_BUF_LEN)
    gyro_buf = deque(maxlen=IMU_BUF_LEN)

    # Placeholder images
    black_frame = np.zeros((VIDEO_H, VIDEO_W, 3), dtype=np.uint8)
    last_rgb = black_frame.copy()
    last_depth_color = black_frame.copy()

    paused = False
    t0_msg = None   # first RGB message timestamp (ns)
    t0_wall = None  # wall clock at first RGB frame (s)
    dirty = False   # whether we have new data to display since last render
    frame_count = 0

    cv2.namedWindow("MCAP Viewer", cv2.WINDOW_NORMAL)

    # Pending messages buffered while we wait for the next RGB frame to render
    pending_depth = []
    pending_imu = []

    for topic, ts_ns, data in stream_mcap(str(mcap_path)):
        if topic == "/oak/imu":
            vals = unpack_imu(bytes(data))
            pending_imu.append(vals)
            continue

        if topic == "/oak/depth":
            pending_depth.append(bytes(data))
            continue

        if topic != "/oak/rgb":
            continue

        # --- Got an RGB frame: render everything accumulated so far ---

        # Process pending depth (keep latest)
        for d_data in pending_depth:
            try:
                last_depth_color = depth_to_color(d_data)
            except ValueError:
                pass
        pending_depth.clear()

        # Process pending IMU
        for vals in pending_imu:
            accel_buf.append(vals[:3])
            gyro_buf.append(vals[3:])
        pending_imu.clear()

        # Decode RGB
        bgr = decode_h265(decoder, bytes(data))
        if bgr is not None:
            last_rgb = bgr

        frame_count += 1

        # Initialize timing on first RGB frame
        if t0_msg is None:
            t0_msg = ts_ns
            t0_wall = time.monotonic()

        # --- Pace playback to real-time ---
        if not paused:
            target_wall = (ts_ns - t0_msg) / 1e9  # seconds since start in message time
            actual_wall = time.monotonic() - t0_wall
            drift = target_wall - actual_wall
            if drift > 0.001:
                # We're ahead of real-time; sleep to catch up
                # But check for key events periodically so pause/quit stays responsive
                remaining = drift
                while remaining > 0:
                    wait = min(remaining, 0.03)
                    key = cv2.waitKey(max(1, int(wait * 1000))) & 0xFF
                    if key == ord("q"):
                        cv2.destroyAllWindows()
                        print(f"Done. ({frame_count} RGB frames)")
                        return
                    elif key == ord(" "):
                        paused = True
                        break
                    remaining -= wait

        # Compose display
        top = np.hstack([last_rgb, last_depth_color])
        bottom = draw_imu_plot(accel_buf, gyro_buf)
        frame = np.vstack([top, bottom])
        cv2.imshow("MCAP Viewer", frame)

        # Handle pause loop
        while paused:
            key = cv2.waitKey(50) & 0xFF
            if key == ord("q"):
                cv2.destroyAllWindows()
                print(f"Done. ({frame_count} RGB frames)")
                return
            elif key == ord(" "):
                paused = False
                # Reset timing so we don't fast-forward after unpause
                t0_msg = ts_ns
                t0_wall = time.monotonic()

        # Minimal waitKey to process window events when not sleeping above
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        elif key == ord(" "):
            paused = True

    cv2.destroyAllWindows()
    print(f"Done. ({frame_count} RGB frames)")


if __name__ == "__main__":
    main()
