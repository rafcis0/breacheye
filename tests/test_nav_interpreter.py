from __future__ import annotations

import pytest

from breacheye.models import CommandType
from breacheye.nav_interpreter import NavInterpreter
from breacheye.rafa.schemas import NavigationAction, NavigationDecision

# All NavigationAction literal values
ALL_ACTIONS: list[NavigationAction] = [
    "move_forward",
    "move_back",
    "move_left",
    "move_right",
    "move_up",
    "move_down",
    "rotate_left",
    "rotate_right",
    "hover",
    "land",
]


@pytest.fixture
def interp() -> NavInterpreter:
    return NavInterpreter()


def make_decision(
    action: NavigationAction,
    params: dict | None = None,
    confidence: float = 0.8,
    exploration_state: str = "exploring",
) -> NavigationDecision:
    return NavigationDecision(
        action=action,
        params=params or {},
        confidence=confidence,
        reasoning="test",
        exploration_state=exploration_state,
    )


def test_map_forward(interp: NavInterpreter) -> None:
    decision = make_decision(
        "move_forward",
        params={"distance_cm": 50, "speed_cm_s": 30},
        confidence=0.8,
    )
    cmd = interp._map_action(decision)

    assert cmd.type == CommandType.RC_CONTROL
    assert cmd.issued_by == "nav_interpreter"
    assert cmd.payload is not None
    assert cmd.payload.forward_back == 30
    assert cmd.payload.left_right == 0
    assert cmd.payload.up_down == 0
    assert cmd.payload.yaw == 0
    # 50/30*1000 = 1667, clamped to 800
    assert cmd.payload.duration_ms == 800
    assert cmd.ttl_ms == 1000  # min(1200, 800+200)


def test_all_actions_produce_valid_commands(interp: NavInterpreter) -> None:
    for action in ALL_ACTIONS:
        decision = make_decision(action, confidence=0.8)
        cmd = interp._map_action(decision)

        assert cmd is not None, f"no command for action={action}"
        assert cmd.issued_by == "nav_interpreter"

        if action == "hover":
            assert cmd.type == CommandType.HOVER
            assert cmd.payload is None
        elif action == "land":
            assert cmd.type == CommandType.LAND
            assert cmd.payload is None
        else:
            assert cmd.type == CommandType.RC_CONTROL
            assert cmd.payload is not None


def test_rotate_uses_degrees(interp: NavInterpreter) -> None:
    decision = make_decision(
        "rotate_right",
        params={"degrees": 45},
        confidence=0.9,
    )
    cmd = interp._map_action(decision)

    assert cmd.type == CommandType.RC_CONTROL
    assert cmd.payload is not None
    assert cmd.payload.yaw == 25
    # 45/90*1000 = 500
    assert cmd.payload.duration_ms == 500


def test_duration_clamps(interp: NavInterpreter) -> None:
    # Large distance → clamp to 800
    decision_large = make_decision(
        "move_forward",
        params={"distance_cm": 500, "speed_cm_s": 10},
        confidence=0.8,
    )
    cmd_large = interp._map_action(decision_large)
    assert cmd_large.payload is not None
    assert cmd_large.payload.duration_ms == 800

    # Tiny distance → clamp to 100
    decision_tiny = make_decision(
        "move_forward",
        params={"distance_cm": 1, "speed_cm_s": 100},
        confidence=0.8,
    )
    cmd_tiny = interp._map_action(decision_tiny)
    assert cmd_tiny.payload is not None
    assert cmd_tiny.payload.duration_ms == 100


def test_ttl_exceeds_duration(interp: NavInterpreter) -> None:
    for action in ALL_ACTIONS:
        decision = make_decision(action, confidence=0.8)
        cmd = interp._map_action(decision)
        if cmd.ttl_ms is not None and cmd.payload is not None:
            assert cmd.ttl_ms >= cmd.payload.duration_ms + 100, (
                f"ttl_ms={cmd.ttl_ms} not >= duration_ms={cmd.payload.duration_ms}+100 for action={action}"
            )


def test_low_confidence_hovers(interp: NavInterpreter) -> None:
    decision = make_decision("move_forward", confidence=0.3)
    cmd = interp._map_action(decision)

    assert cmd.type == CommandType.HOVER
    assert cmd.payload is None
    assert cmd.issued_by == "nav_interpreter"
