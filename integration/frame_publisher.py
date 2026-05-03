from __future__ import annotations

import argparse
import itertools
import time
from pathlib import Path
from typing import Iterable

from breacheye.rafa.codec import encode_msgpack
from breacheye.rafa.schemas import FrameInput
from breacheye.runlog import RunLogger
from breacheye.video import encode_jpeg


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish Cooper -> Rafa JPEG frames on ZMQ port 5555.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5555)
    parser.add_argument("--fps", type=float, default=5.0)
    parser.add_argument("--frames", type=int, default=0, help="Stop after N frames. 0 means run forever.")
    parser.add_argument("--mock-images", type=Path, help="Directory of image files to loop over.")
    parser.add_argument("--mock-video", type=Path, help="Video file to loop over.")
    parser.add_argument("--video-start-s", type=float, default=0.0, help="Start reading mock video at this timestamp.")
    parser.add_argument("--video-stride", type=int, default=1, help="Read every Nth frame from mock video.")
    parser.add_argument("--harness-url", help="Read JPEG frames from a running harness /frame/latest endpoint.")
    parser.add_argument("--tello", action="store_true", help="Read live frames from djitellopy.Tello.")
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--run-id")
    args = parser.parse_args()

    publisher = FramePublisher(host=args.host, port=args.port, fps=args.fps, log_dir=args.log_dir, run_id=args.run_id)
    if args.harness_url:
        frames = harness_frames(args.harness_url)
    elif args.tello:
        frames = tello_frames()
    elif args.mock_video:
        frames = video_frames(args.mock_video, start_s=args.video_start_s, stride=args.video_stride)
    elif args.mock_images:
        frames = image_frames(args.mock_images)
    else:
        frames = synthetic_frames()
    publisher.publish(frames, limit=args.frames or None)


class FramePublisher:
    def __init__(self, host: str = "127.0.0.1", port: int = 5555, fps: float = 5.0, log_dir: str | None = "logs", run_id: str | None = None) -> None:
        self.endpoint = f"tcp://{host}:{port}"
        self.interval_s = 1.0 / fps if fps > 0 else 0.0
        self.logger = RunLogger("frame_publisher", log_dir=log_dir, run_id=run_id)

    def publish(self, frames: Iterable, limit: int | None = None) -> None:
        import zmq

        context = zmq.Context.instance()
        socket = context.socket(zmq.PUB)
        socket.bind(self.endpoint)
        self.logger.event("publisher_start", endpoint=self.endpoint, interval_s=self.interval_s, limit=limit)
        time.sleep(0.2)
        try:
            for frame_id, frame in enumerate(frames):
                if limit is not None and frame_id >= limit:
                    break
                height, width = frame.shape[:2]
                jpeg_bytes = encode_jpeg(frame)
                payload = frame_payload(frame_id, jpeg_bytes, width=width, height=height)
                socket.send(payload)
                image_path = self.logger.save_bytes("frames", f"frame-{frame_id:08d}.jpg", jpeg_bytes)
                self.logger.event(
                    "frame_published",
                    frame_id=frame_id,
                    width=width,
                    height=height,
                    payload_bytes=len(payload),
                    jpeg_bytes=len(jpeg_bytes),
                    image_path=image_path,
                )
                print(f"published frame_id={frame_id} size={width}x{height}")
                if self.interval_s:
                    time.sleep(self.interval_s)
        finally:
            self.logger.event("publisher_stop")
            socket.close(linger=0)


def frame_payload(frame_id: int, jpeg_bytes: bytes, width: int | None = None, height: int | None = None) -> bytes:
    return encode_msgpack(
        FrameInput(
            frame_id=frame_id,
            timestamp=time.time(),
            width=width,
            height=height,
            jpeg_bytes=jpeg_bytes,
        )
    )


def synthetic_frames(width: int = 960, height: int = 720):
    import cv2
    import numpy as np

    for index in itertools.count():
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:, :] = (24, 28, 32)
        x = 80 + (index * 12) % max(1, width - 240)
        cv2.rectangle(frame, (x, 160), (x + 160, 560), (80, 160, 220), thickness=-1)
        cv2.putText(
            frame,
            f"BreachEye mock frame {index}",
            (40, 80),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (230, 230, 230),
            2,
            cv2.LINE_AA,
        )
        yield frame


def image_frames(directory: Path):
    import cv2

    paths = sorted(
        path
        for path in directory.iterdir()
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    )
    if not paths:
        raise FileNotFoundError(f"no image files found in {directory}")
    for path in itertools.cycle(paths):
        frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError(f"failed to read image {path}")
        yield frame


def video_frames(path: Path, start_s: float = 0.0, stride: int = 1):
    import cv2

    if stride < 1:
        raise ValueError("video stride must be >= 1")
    while True:
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            raise ValueError(f"failed to open video {path}")
        if start_s > 0:
            capture.set(cv2.CAP_PROP_POS_MSEC, start_s * 1000)
        try:
            index = 0
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                if index % stride == 0:
                    yield frame
                index += 1
        finally:
            capture.release()


def harness_frames(frame_url: str, timeout_s: float = 2.0):
    import cv2
    import httpx
    import numpy as np

    with httpx.Client(timeout=timeout_s) as client:
        while True:
            try:
                response = client.get(frame_url)
            except httpx.HTTPError:
                time.sleep(0.1)
                continue
            if response.status_code == 404:
                time.sleep(0.1)
                continue
            response.raise_for_status()
            data = np.frombuffer(response.content, dtype=np.uint8)
            frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
            if frame is None:
                raise ValueError(f"harness returned undecodable JPEG from {frame_url}")
            yield frame


def tello_frames():
    from djitellopy import Tello

    tello = Tello()
    tello.connect()
    tello.streamon()
    reader = tello.get_frame_read()
    try:
        while True:
            frame = reader.frame
            if frame is not None:
                yield frame
            time.sleep(1 / 30)
    finally:
        tello.streamoff()
        tello.end()


if __name__ == "__main__":
    main()
