import numpy as np
import pytest

from breacheye.rafa.schemas import BBox2D, DepthOutput, Detection, DetectionOutput, FrameInput
from breacheye.rafa.spatial_context import compute_doorway_centering_hints


def _doorway(det_id: str, x1: int, x2: int) -> Detection:
    return Detection(
        id=det_id,
        category="T1-01",
        label="Entry Point",
        confidence=0.9,
        bbox_2d=BBox2D(x1=x1, y1=20, x2=x2, y2=80),
        threat_level="CLEAR",
        detection_model="test",
    )


def test_doorway_centering_hint_left_offset_and_depth() -> None:
    meta = FrameInput(frame_id=4, timestamp=1.0, width=100, height=100, jpeg_bytes=b"jpg")
    detections = DetectionOutput(frame_id=4, detections=[_doorway("door-left", 10, 30)], processing_ms=1)
    depth_values = np.full((10, 10), 0.7, dtype=np.float32)
    depth_values[3:8, 1:3] = 0.42
    depth = DepthOutput(frame_id=4, shape=depth_values.shape, depth_bytes=depth_values.tobytes())

    hints = compute_doorway_centering_hints(meta=meta, detections=detections, depth=depth, threshold=0.15)

    assert len(hints) == 1
    assert hints[0].doorway_detection_id == "door-left"
    assert hints[0].offset_ratio == -0.6
    assert hints[0].centered is False
    assert hints[0].suggested_action == "rotate_left"
    assert hints[0].approach_depth == pytest.approx(0.42)


def test_doorway_centering_hint_centered() -> None:
    meta = FrameInput(frame_id=5, timestamp=1.0, width=100, height=100, jpeg_bytes=b"jpg")
    detections = DetectionOutput(frame_id=5, detections=[_doorway("door-center", 42, 58)], processing_ms=1)

    hints = compute_doorway_centering_hints(meta=meta, detections=detections, depth=None, threshold=0.15)

    assert hints[0].centered is True
    assert hints[0].offset_ratio == 0.0
    assert hints[0].suggested_action == "hover"


def test_non_doorway_detections_do_not_emit_hints() -> None:
    meta = FrameInput(frame_id=6, timestamp=1.0, width=100, height=100, jpeg_bytes=b"jpg")
    detections = DetectionOutput(
        frame_id=6,
        detections=[
            Detection(
                id="room",
                category="ROOM",
                label="Room",
                confidence=0.8,
                bbox_2d=BBox2D(x1=0, y1=0, x2=100, y2=100),
                threat_level="INFO",
                detection_model="test",
            )
        ],
        processing_ms=1,
    )

    assert compute_doorway_centering_hints(meta=meta, detections=detections, depth=None) == []
