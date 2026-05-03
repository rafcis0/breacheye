import numpy as np
import pytest

from breacheye.rafa.models import (
    _depth_anything_to_relative_far,
    _depth_prompt_hint,
    _extract_action,
    _extract_decision_fields,
)
from breacheye.rafa.schemas import DepthOutput


def test_extract_action_prefers_json_action_over_prompt_echo() -> None:
    text = 'Allowed: move_forward, rotate_left, hover. {"action":"rotate_right","confidence":0.8}'

    assert _extract_action(text) == "rotate_right"


def test_extract_decision_fields_uses_model_confidence() -> None:
    text = 'Allowed: move_forward, rotate_left, hover. {"action":"move_forward","confidence":0.44}'

    assert _extract_decision_fields(text) == ("move_forward", 0.44)


def test_extract_decision_fields_clamps_confidence() -> None:
    text = '{"action":"rotate_right","confidence":2.0}'

    assert _extract_decision_fields(text) == ("rotate_right", 1.0)


def test_extract_decision_fields_fallback_is_conservative_for_motion() -> None:
    assert _extract_decision_fields("I would rotate_left, otherwise hover.") == ("rotate_left", 0.45)


def test_extract_action_fallback_prefers_motion_before_hover() -> None:
    assert _extract_action("I would rotate_left, otherwise hover.") == "rotate_left"


def test_depth_prompt_hint_marks_marginal_center_as_blocked(monkeypatch) -> None:
    monkeypatch.setenv("BREACHEYE_NAV_MIN_FORWARD_CLEARANCE_M", "0.45")
    depth_values = np.ones((6, 6), dtype=np.float32) * 0.4
    depth = DepthOutput(frame_id=1, shape=depth_values.shape, depth_bytes=depth_values.tobytes())

    hint = _depth_prompt_hint(depth)

    assert "0.400" in hint
    assert "blocked or marginal" in hint


def test_depth_anything_normalization_matches_relative_far_contract() -> None:
    raw_inverse_depth = np.array([[0.0, 10.0]], dtype=np.float32)

    relative = _depth_anything_to_relative_far(raw_inverse_depth, near=0.0, far=10.0)

    assert relative[0, 0] == pytest.approx(1.0)
    assert relative[0, 1] == pytest.approx(0.0)
