import numpy as np
import pytest

from breacheye.rafa.adapters import SafeRuleNavigator, StubDepthEstimator, StubDetector
from breacheye.rafa.schemas import ALLOWED_NAVIGATION_ACTIONS, FrameInput
from breacheye.video import encode_jpeg


@pytest.mark.asyncio
async def test_stub_adapters_validate_outputs_and_nav_action_is_allowed() -> None:
    frame = np.zeros((12, 16, 3), dtype=np.uint8)
    meta = FrameInput(frame_id=7, timestamp=1.0, jpeg_bytes=encode_jpeg(frame))

    detections = await StubDetector().detect(frame, meta)
    depth = await StubDepthEstimator().estimate(frame, meta)
    navigation = await SafeRuleNavigator().decide(frame, meta, detections, depth)

    assert detections.frame_id == 7
    assert detections.detections[0].bbox_2d.x2 <= 16
    assert depth.shape == (12, 16)
    assert navigation.decision.action in ALLOWED_NAVIGATION_ACTIONS
