import numpy as np
import pytest

from breacheye.rafa.orchestrator import RafaPipeline, RafaPipelineConfig
from breacheye.rafa.schemas import (
    BBox2D,
    DepthOutput,
    Detection,
    DetectionOutput,
    DoorwayCenteringHint,
    FrameInput,
)


class FailingNavigator:
    name = "failing-nav"

    async def decide(self, *_args, **_kwargs):
        raise AssertionError("VLM should be bypassed during doorway transit")


def _frame(frame_id: int) -> FrameInput:
    return FrameInput(frame_id=frame_id, timestamp=1.0, width=100, height=100, jpeg_bytes=b"jpg")


def _detection(frame_id: int, hint: DoorwayCenteringHint) -> DetectionOutput:
    return DetectionOutput(
        frame_id=frame_id,
        detections=[
            Detection(
                id=hint.doorway_detection_id,
                category="T1-01",
                label="Entry Point",
                confidence=0.9,
                bbox_2d=BBox2D(x1=40, y1=10, x2=60, y2=90),
                threat_level="CLEAR",
                detection_model="test",
            )
        ],
        doorway_centering_hints=[hint],
        processing_ms=1,
    )


def _hint(frame_id: int, *, offset: float = 0.0, depth: float = 0.8) -> DoorwayCenteringHint:
    return DoorwayCenteringHint(
        frame_id=frame_id,
        doorway_detection_id="door-1",
        offset_ratio=offset,
        centered=abs(offset) <= 0.15,
        approach_depth=depth,
        suggested_action="hover" if abs(offset) <= 0.15 else "rotate_left",
    )


def _depth(value: float = 0.8) -> DepthOutput:
    values = np.full((10, 10), value, dtype=np.float32)
    return DepthOutput(frame_id=1, shape=values.shape, depth_bytes=values.tobytes())


@pytest.mark.asyncio
async def test_pipeline_bypasses_vlm_for_full_doorway_transit(tmp_path) -> None:
    pipeline = RafaPipeline(RafaPipelineConfig(log_dir=str(tmp_path), run_id="transit"))
    pipeline.navigator = FailingNavigator()
    actions = []
    states = []

    first = _hint(1, offset=-0.4)
    nav = await pipeline._safe_navigation(None, _frame(1), _detection(1, first), _depth(0.8))
    actions.append(nav.decision.action)
    states.append(nav.decision.exploration_state)

    for frame_id, approach_depth in [(2, 0.8), (3, 0.25), (4, 0.25), (5, 0.25), (6, 0.25), (7, 0.25)]:
        hint = _hint(frame_id, offset=0.0, depth=approach_depth)
        nav = await pipeline._safe_navigation(None, _frame(frame_id), _detection(frame_id, hint), _depth(0.8))
        actions.append(nav.decision.action)
        states.append(nav.decision.exploration_state)

    assert actions[:2] == ["rotate_left", "move_forward"]
    assert "doorway_passing_through" in states
    assert states[-1] == "doorway_resumed"
    assert pipeline._search_tactic.node_id == 1


@pytest.mark.asyncio
async def test_doorway_transit_aborts_on_close_forward_obstacle(tmp_path) -> None:
    pipeline = RafaPipeline(RafaPipelineConfig(log_dir=str(tmp_path), run_id="transit-abort"))
    centered = _hint(1, offset=0.0, depth=0.8)
    await pipeline._safe_navigation(None, _frame(1), _detection(1, centered), _depth(0.8))

    close_depth = _depth(0.05)
    nav = await pipeline._safe_navigation(None, _frame(2), _detection(2, centered), close_depth)

    assert nav.decision.action == "hover"
    assert nav.decision.exploration_state == "doorway_aborted"
