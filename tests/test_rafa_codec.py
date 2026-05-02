import numpy as np

from breacheye.rafa.codec import decode_depth, decode_detection, decode_frame, decode_health, decode_navigation, encode_json, encode_msgpack
from breacheye.rafa.schemas import (
    BBox2D,
    DepthOutput,
    Detection,
    DetectionOutput,
    FrameInput,
    HealthOutput,
    ModelStatus,
    NavigationDecision,
    NavigationOutput,
)


def test_contract_codecs_round_trip_frame_depth_msgpack_and_json_outputs() -> None:
    frame = FrameInput(frame_id=1, timestamp=1.25, jpeg_bytes=b"jpeg")
    detection = DetectionOutput(
        frame_id=1,
        detections=[
            Detection(
                id="det-1",
                category="ROOM",
                label="Room/Open Area",
                confidence=0.5,
                bbox_2d=BBox2D(x1=0, y1=0, x2=10, y2=10),
                threat_level="INFO",
                detection_model="stub",
            )
        ],
        processing_ms=1,
    )
    depth_array = np.zeros((2, 3), dtype=np.float32)
    depth = DepthOutput(frame_id=1, shape=(2, 3), depth_bytes=depth_array.tobytes())
    navigation = NavigationOutput(
        frame_id=1,
        decision=NavigationDecision(action="hover", params={"duration_ms": 500}, confidence=1.0),
    )
    health = HealthOutput(
        models_loaded={
            "moondream": ModelStatus(status="stub", active="stub-detector"),
            "depth_anything_v2": ModelStatus(status="stub", active="stub-depth"),
            "qwen3_vl": ModelStatus(status="stub", active="safe-rule-navigator"),
        }
    )

    assert decode_frame(encode_msgpack(frame)) == frame
    assert decode_detection(encode_json(detection)) == detection
    assert decode_depth(encode_msgpack(depth)) == depth
    assert decode_navigation(encode_json(navigation)) == navigation
    assert decode_health(encode_json(health)) == health
