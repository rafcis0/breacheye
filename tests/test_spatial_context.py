import numpy as np

from breacheye.rafa.schemas import BBox2D, DepthOutput, Detection, DetectionOutput, FrameInput
from breacheye.rafa.spatial_context import build_spatial_context, summarize_spatial_context


def test_build_spatial_context_from_current_frame_outputs_frontier_and_objects() -> None:
    meta = FrameInput(frame_id=7, timestamp=1.0, width=90, height=60, jpeg_bytes=b"jpg")
    detections = DetectionOutput(
        frame_id=7,
        processing_ms=1,
        detections=[
            Detection(
                id="person-1",
                category="T3-01",
                label="person",
                confidence=0.8,
                bbox_2d=BBox2D(x1=5, y1=5, x2=20, y2=30),
                threat_level="INFO",
                detection_model="test",
            )
        ],
    )
    depth_values = np.ones((6, 9), dtype=np.float32) * 0.7
    depth = DepthOutput(frame_id=7, shape=depth_values.shape, depth_bytes=depth_values.tobytes())

    context = build_spatial_context(meta=meta, detections=detections, depth=depth, recent_actions=["hover"])

    assert context.frame_id == 7
    assert context.current_pose.source == "unavailable"
    assert context.looking_at.direction_label == "forward"
    assert context.unexplored_frontiers[0].label == "open forward view"
    assert context.known_objects[0].relative_position == "left"
    assert context.recent_actions == ["hover"]
    assert summarize_spatial_context(context)["frontiers"] == 1


def test_spatial_context_ignores_isolated_depth_noise() -> None:
    meta = FrameInput(frame_id=8, timestamp=1.0, width=90, height=60, jpeg_bytes=b"jpg")
    detections = DetectionOutput(frame_id=8, processing_ms=1, detections=[])
    depth_values = np.ones((60, 90), dtype=np.float32) * 0.7
    depth_values[30, 45] = 0.01
    depth = DepthOutput(frame_id=8, shape=depth_values.shape, depth_bytes=depth_values.tobytes())

    context = build_spatial_context(meta=meta, detections=detections, depth=depth, recent_actions=[])

    assert context.looking_at.nearest_obstacle_m > 0.35
    assert context.unexplored_frontiers


def test_spatial_context_frontier_clearance_is_configurable() -> None:
    meta = FrameInput(frame_id=9, timestamp=1.0, width=90, height=60, jpeg_bytes=b"jpg")
    detections = DetectionOutput(frame_id=9, processing_ms=1, detections=[])
    depth_values = np.ones((60, 90), dtype=np.float32) * 0.5
    depth = DepthOutput(frame_id=9, shape=depth_values.shape, depth_bytes=depth_values.tobytes())

    cautious = build_spatial_context(
        meta=meta,
        detections=detections,
        depth=depth,
        recent_actions=[],
        frontier_clearance=0.6,
    )
    permissive = build_spatial_context(
        meta=meta,
        detections=detections,
        depth=depth,
        recent_actions=[],
        frontier_clearance=0.4,
    )

    assert cautious.unexplored_frontiers == []
    assert permissive.unexplored_frontiers
