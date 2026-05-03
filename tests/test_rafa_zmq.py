import asyncio
import json
import socket

import numpy as np
import pytest

from breacheye.rafa.codec import (
    decode_depth,
    decode_detection,
    decode_health,
    decode_navigation,
    encode_msgpack,
)
from breacheye.rafa.orchestrator import RafaPipeline, RafaPipelineConfig
from breacheye.rafa.schemas import ALLOWED_NAVIGATION_ACTIONS, FrameInput
from breacheye.video import encode_jpeg


@pytest.mark.asyncio
async def test_in_process_zmq_stub_pipeline_publishes_all_outputs(tmp_path) -> None:
    import zmq
    import zmq.asyncio

    ports = [_free_port() for _ in range(5)]
    frame_port, detection_port, depth_port, navigation_port, health_port = ports
    context = zmq.asyncio.Context.instance()

    input_pub = context.socket(zmq.PUB)
    input_pub.bind(f"tcp://127.0.0.1:{frame_port}")

    subscribers = {}
    for name, port in {
        "detections": detection_port,
        "depth": depth_port,
        "navigation": navigation_port,
        "health": health_port,
    }.items():
        socket_ = context.socket(zmq.SUB)
        socket_.setsockopt(zmq.SUBSCRIBE, b"")
        socket_.connect(f"tcp://127.0.0.1:{port}")
        subscribers[name] = socket_

    pipeline = RafaPipeline(
        RafaPipelineConfig(
            mode="stub",
            frame_port=frame_port,
            detection_port=detection_port,
            depth_port=depth_port,
            navigation_port=navigation_port,
            health_port=health_port,
            health_interval_s=0.0,
            log_dir=str(tmp_path),
            run_id="zmq-test",
        )
    )
    await pipeline.start()
    try:
        await asyncio.sleep(0.2)
        frame = np.zeros((8, 10, 3), dtype=np.uint8)
        payload = encode_msgpack(FrameInput(frame_id=3, timestamp=1.0, jpeg_bytes=encode_jpeg(frame)))
        for _ in range(3):
            await input_pub.send(payload)
            await asyncio.sleep(0.05)

        processed = False
        for _ in range(10):
            processed = await pipeline.run_once()
            if processed:
                break
        assert processed is True

        detection = decode_detection(await asyncio.wait_for(subscribers["detections"].recv(), 2))
        depth = decode_depth(await asyncio.wait_for(subscribers["depth"].recv(), 2))
        navigation = decode_navigation(await asyncio.wait_for(subscribers["navigation"].recv(), 2))
        health = decode_health(await asyncio.wait_for(subscribers["health"].recv(), 2))

        assert detection.frame_id == 3
        assert depth.frame_id == 3
        assert navigation.decision.action in ALLOWED_NAVIGATION_ACTIONS
        assert health.pipeline_status in {"ready", "degraded"}
        assert (tmp_path / "zmq-test" / "rafa" / "frames" / "frame-00000003.jpg").exists()
        assert (tmp_path / "zmq-test" / "rafa" / "depth" / "frame-00000003.png").exists()
        assert (tmp_path / "zmq-test" / "rafa" / "depth_raw" / "frame-00000003.npy").exists()
        events = [
            json.loads(line)
            for line in (tmp_path / "zmq-test-rafa.jsonl").read_text().splitlines()
        ]
        context_events = [event for event in events if event["event"] == "navigation_context_built"]
        assert context_events
        assert context_events[-1]["frame_id"] == 3
        assert context_events[-1]["context"]["source"] == "stub_from_current_frame"
    finally:
        await pipeline.stop()
        input_pub.close(linger=0)
        for socket_ in subscribers.values():
            socket_.close(linger=0)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
