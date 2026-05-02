"""Demo playback — publishes pre-recorded frames and time-synced mock detections to ZMQ.

Reads a video file and a detection JSON, then replays them in sync over ZMQ ports 5555
(frames, msgpack) and 5556 (detections, JSON). Use as an insurance policy when the Tello
WiFi or live models are unavailable during a demo.

Usage:
    python demo/playback.py --video demo/sample.mp4
    python demo/playback.py --video demo/sample.mp4 --loop --fps 30
    python demo/playback.py --video demo/sample.mp4 --detections demo/mock_detections.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import zmq

# Ensure the package is importable when run from repo root
sys.path.insert(0, "src")

from breacheye.rafa.codec import encode_msgpack
from breacheye.rafa.schemas import BBox2D, Detection, DetectionOutput, FrameInput
from breacheye.video import encode_jpeg

DEFAULT_DETECTIONS = "demo/mock_detections.json"
DEFAULT_FRAME_PORT = 5555
DEFAULT_DETECTION_PORT = 5556


def load_detections(path: str) -> dict[int, DetectionOutput]:
    """Load and validate detection JSON. Keys are frame_ids (stored as strings in JSON)."""
    p = Path(path)
    if not p.exists():
        print(f"[playback] ERROR: detection file not found: {path}")
        sys.exit(1)

    with p.open() as f:
        raw = json.load(f)

    parsed: dict[int, DetectionOutput] = {}
    errors: list[str] = []
    for key, entry in raw.items():
        try:
            frame_id = int(key)
            output = DetectionOutput(
                frame_id=frame_id,
                timestamp=time.time(),
                detections=entry.get("detections", []),
                processing_ms=entry.get("processing_ms", 0),
            )
            parsed[frame_id] = output
        except Exception as exc:
            errors.append(f"  frame_id={key}: {exc}")

    if errors:
        print(f"[playback] ERROR: detection JSON failed schema validation ({len(errors)} entries):")
        for e in errors:
            print(e)
        sys.exit(1)

    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Publish pre-recorded frames + synced detections to ZMQ."
    )
    parser.add_argument("--video", required=True, help="Path to video file")
    parser.add_argument(
        "--detections",
        default=DEFAULT_DETECTIONS,
        help=f"Path to detection JSON (default: {DEFAULT_DETECTIONS})",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=None,
        help="Override video FPS (default: use video native FPS)",
    )
    parser.add_argument("--loop", action="store_true", help="Loop video when it ends")
    parser.add_argument("--frame-port", type=int, default=DEFAULT_FRAME_PORT)
    parser.add_argument("--detection-port", type=int, default=DEFAULT_DETECTION_PORT)
    args = parser.parse_args()

    video_path = Path(args.video)
    if not video_path.exists():
        print(f"[playback] ERROR: video file not found: {args.video}")
        sys.exit(1)

    detections = load_detections(args.detections)

    import cv2

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"[playback] ERROR: could not open video: {args.video}")
        sys.exit(1)

    native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    fps = args.fps if args.fps is not None else native_fps
    interval_s = 1.0 / fps if fps > 0 else 0.0

    print("[playback] ---")
    print(f"[playback] video:          {args.video}")
    print(f"[playback] detections:     {args.detections} ({len(detections)} scripted frames)")
    print(f"[playback] fps:            {fps:.1f}")
    print(f"[playback] loop:           {args.loop}")
    print(f"[playback] frame port:     {args.frame_port}")
    print(f"[playback] detection port: {args.detection_port}")
    print("[playback] ---")

    context = zmq.Context.instance()
    frame_sock = context.socket(zmq.PUB)
    frame_sock.bind(f"tcp://127.0.0.1:{args.frame_port}")
    det_sock = context.socket(zmq.PUB)
    det_sock.bind(f"tcp://127.0.0.1:{args.detection_port}")

    # Brief pause so subscribers can connect before the first publish
    time.sleep(0.2)

    frame_id = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                if args.loop:
                    cap.release()
                    cap = cv2.VideoCapture(str(video_path))
                    if not cap.isOpened():
                        print("[playback] ERROR: failed to reopen video for loop")
                        break
                    ok, frame = cap.read()
                    if not ok:
                        print("[playback] ERROR: could not read first frame on loop restart")
                        break
                else:
                    print("[playback] end of video")
                    break

            height, width = frame.shape[:2]
            jpeg_bytes = encode_jpeg(frame)

            frame_payload = encode_msgpack(
                FrameInput(
                    frame_id=frame_id,
                    timestamp=time.time(),
                    width=width,
                    height=height,
                    jpeg_bytes=jpeg_bytes,
                )
            )
            frame_sock.send(frame_payload)

            if frame_id in detections:
                det_out = detections[frame_id]
                # Refresh timestamp for accurate replay timing
                det_out = DetectionOutput(
                    frame_id=frame_id,
                    timestamp=time.time(),
                    detections=det_out.detections,
                    processing_ms=det_out.processing_ms,
                )
                det_count = len(det_out.detections)
            else:
                det_out = DetectionOutput(
                    frame_id=frame_id,
                    timestamp=time.time(),
                    detections=[],
                    processing_ms=0,
                )
                det_count = 0

            det_sock.send_string(json.dumps(det_out.model_dump()))

            if frame_id % 10 == 0:
                print(f"[playback] frame={frame_id:04d}  detections={det_count}  fps={fps:.1f}")

            frame_id += 1

            if interval_s:
                time.sleep(interval_s)

    except KeyboardInterrupt:
        print("\n[playback] interrupted")
    finally:
        cap.release()
        frame_sock.close(linger=0)
        det_sock.close(linger=0)
        print("[playback] sockets closed")


if __name__ == "__main__":
    main()
