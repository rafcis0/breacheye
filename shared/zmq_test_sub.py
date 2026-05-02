from __future__ import annotations

import argparse
import json

from breacheye.rafa.codec import decode_depth, decode_frame


def main() -> None:
    parser = argparse.ArgumentParser(description="Subscribe to a BreachEye ZMQ channel and print decoded messages.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument(
        "--channel",
        choices=["frames", "detections", "depth", "navigation", "health", "raw"],
        default="raw",
    )
    parser.add_argument("--count", type=int, default=1)
    args = parser.parse_args()

    import zmq

    context = zmq.Context.instance()
    socket = context.socket(zmq.SUB)
    socket.setsockopt(zmq.SUBSCRIBE, b"")
    socket.connect(f"tcp://{args.host}:{args.port}")
    try:
        for _ in range(args.count):
            data = socket.recv()
            print(decode_payload(args.channel, data))
    finally:
        socket.close(linger=0)


def decode_payload(channel: str, data: bytes) -> str:
    if channel == "frames":
        frame = decode_frame(data)
        return json.dumps(
            {
                "frame_id": frame.frame_id,
                "timestamp": frame.timestamp,
                "width": frame.width,
                "height": frame.height,
                "jpeg_bytes": len(frame.jpeg_bytes),
            },
            indent=2,
        )
    if channel == "depth":
        depth = decode_depth(data)
        return json.dumps(
            {
                "frame_id": depth.frame_id,
                "timestamp": depth.timestamp,
                "shape": depth.shape,
                "dtype": depth.dtype,
                "unit": depth.unit,
                "depth_bytes": len(depth.depth_bytes),
            },
            indent=2,
        )
    if channel in {"detections", "navigation", "health"}:
        return json.dumps(json.loads(data.decode("utf-8")), indent=2)
    return data.decode("utf-8", errors="replace")


if __name__ == "__main__":
    main()
