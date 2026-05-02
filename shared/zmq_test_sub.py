from __future__ import annotations

import argparse
import json

from breacheye.rafa.codec import decode_depth, decode_frame
from breacheye.runlog import RunLogger


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
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--run-id")
    args = parser.parse_args()
    logger = RunLogger(f"subscriber_{args.channel}_{args.port}", log_dir=args.log_dir, run_id=args.run_id)

    import zmq

    context = zmq.Context.instance()
    socket = context.socket(zmq.SUB)
    socket.setsockopt(zmq.SUBSCRIBE, b"")
    socket.connect(f"tcp://{args.host}:{args.port}")
    logger.event("subscriber_start", host=args.host, port=args.port, channel=args.channel, count=args.count)
    try:
        for _ in range(args.count):
            data = socket.recv()
            decoded = decode_payload(args.channel, data)
            logger.event("message_received", bytes=len(data), decoded=decoded)
            print(decoded)
    finally:
        logger.event("subscriber_stop")
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
