"""Tests for NavInterpreter depth-aware forward guard."""
from __future__ import annotations

import pytest
from breacheye.nav_interpreter import NavInterpreter
from breacheye.rafa.schemas import NavigationDecision


def _make_interpreter(**kwargs) -> NavInterpreter:
    return NavInterpreter(
        endpoint="tcp://127.0.0.1:5558",
        command_url="http://localhost:8000/commands",
        log_dir=None,
        **kwargs,
    )


def _make_decision(action: str = "move_forward", confidence: float = 0.9) -> NavigationDecision:
    return NavigationDecision(
        action=action,
        params={"distance_cm": 40},
        confidence=confidence,
        reasoning="test",
        exploration_state="exploring",
    )


def _make_alert(nearest: float = 0.3, blocked: bool = True, threshold: float = 0.45) -> dict:
    return {
        "frame_id": 1,
        "timestamp": 1.0,
        "nearest_obstacle_m": nearest,
        "zones": {"left": 0.8, "center": nearest, "right": 0.7},
        "blocked": blocked,
        "threshold": threshold,
    }


def test_forward_blocked_when_alert_blocked():
    """move_forward replaced with rotate_right when alert.blocked=True."""
    interp = _make_interpreter()
    interp._latest_alert = _make_alert(nearest=0.2, blocked=True)
    result = interp._guard_action(_make_decision("move_forward"))
    assert result == "rotate_right"


def test_forward_blocked_when_nearest_below_threshold():
    """move_forward blocked when nearest < depth_threshold, even if blocked=False."""
    interp = _make_interpreter()
    interp._latest_alert = _make_alert(nearest=0.3, blocked=False)
    interp._depth_threshold = 0.45
    result = interp._guard_action(_make_decision("move_forward"))
    assert result == "rotate_right"


def test_forward_allowed_when_clear():
    """move_forward passes through when alert shows clear."""
    interp = _make_interpreter()
    interp._latest_alert = _make_alert(nearest=0.8, blocked=False)
    result = interp._guard_action(_make_decision("move_forward"))
    assert result == "move_forward"


def test_forward_allowed_when_no_alert():
    """Graceful degradation: no alert received yet -> allow forward."""
    interp = _make_interpreter()
    assert interp._latest_alert is None
    result = interp._guard_action(_make_decision("move_forward"))
    assert result == "move_forward"


def test_non_forward_actions_unaffected():
    """Depth guard only applies to move_forward."""
    interp = _make_interpreter()
    interp._latest_alert = _make_alert(nearest=0.1, blocked=True)
    assert interp._guard_action(_make_decision("rotate_right")) == "rotate_right"
    assert interp._guard_action(_make_decision("hover")) == "hover"
    assert interp._guard_action(_make_decision("move_left")) == "move_left"


def test_streak_guards_still_work_after_depth_passes():
    """After depth guard passes, streak guard still triggers."""
    interp = _make_interpreter()
    interp._latest_alert = _make_alert(nearest=0.8, blocked=False)
    interp._max_forward_streak = 2

    assert interp._guard_action(_make_decision("move_forward")) == "move_forward"
    assert interp._guard_action(_make_decision("move_forward")) == "move_forward"
    # Third should trigger streak guard
    result = interp._guard_action(_make_decision("move_forward"))
    assert result == "rotate_right"


def test_depth_guard_resets_forward_streak():
    """When depth guard fires, forward streak resets to 0."""
    interp = _make_interpreter()
    interp._max_forward_streak = 3

    # Build up streak with clear alerts
    interp._latest_alert = _make_alert(nearest=0.8, blocked=False)
    interp._guard_action(_make_decision("move_forward"))
    interp._guard_action(_make_decision("move_forward"))
    assert interp._forward_streak == 2

    # Now block — streak should reset
    interp._latest_alert = _make_alert(nearest=0.2, blocked=True)
    result = interp._guard_action(_make_decision("move_forward"))
    assert result == "rotate_right"
    assert interp._forward_streak == 0


def test_transit_decision_skips_forward_streak_guard():
    """Doorway transit pulses should not trip normal anti-forward-streak scan logic."""
    interp = _make_interpreter()
    interp._latest_alert = _make_alert(nearest=0.8, blocked=False)
    interp._max_forward_streak = 1
    decision = NavigationDecision(
        action="move_forward",
        params={"distance_cm": 25, "transit_phase": "passing_through", "relax_depth_guard": 1},
        confidence=0.8,
        reasoning="passing through doorway",
        exploration_state="doorway_passing_through",
    )

    assert interp._guard_action(decision) == "move_forward"
    assert interp._guard_action(decision) == "move_forward"


def test_transit_relaxed_depth_uses_center_zone_not_side_doorframe():
    """Close side zones from a doorframe should not block pass-through if center is clear."""
    interp = _make_interpreter()
    interp._latest_alert = {
        "frame_id": 1,
        "nearest_obstacle_m": 0.05,
        "zones": {"left": 0.05, "center": 0.7, "right": 0.08},
        "blocked": True,
        "threshold": 0.45,
    }
    decision = NavigationDecision(
        action="move_forward",
        params={"distance_cm": 25, "transit_phase": "passing_through", "relax_depth_guard": 1},
        confidence=0.8,
        reasoning="passing through doorway",
        exploration_state="doorway_passing_through",
    )

    assert interp._guard_action(decision) == "move_forward"
