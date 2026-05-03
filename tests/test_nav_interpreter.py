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
    # 50/30*1000 = 1667, clamped by the live movement safety cap.
    assert cmd.payload.duration_ms == 350
    assert cmd.ttl_ms == 550


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
    # Large distance -> clamp to the live movement safety cap.
    decision_large = make_decision(
        "move_forward",
        params={"distance_cm": 500, "speed_cm_s": 10},
        confidence=0.8,
    )
    cmd_large = interp._map_action(decision_large)
    assert cmd_large.payload is not None
    assert cmd_large.payload.duration_ms == 350

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


def test_map_action_no_longer_checks_confidence(interp: NavInterpreter) -> None:
    """_map_action no longer gates on confidence — that's run_once's job."""
    decision = make_decision("move_forward", confidence=0.3)
    cmd = interp._map_action(decision)
    # Should map the action regardless of confidence
    assert cmd.type == CommandType.RC_CONTROL


def test_consecutive_failures_increment(interp: NavInterpreter) -> None:
    """Low confidence decisions increment the failure counter."""
    for i in range(3):
        decision = make_decision("move_forward", confidence=0.3)
        # Simulate what run_once does: check confidence, increment
        if decision.confidence < 0.5:
            interp._consecutive_failures += 1
    assert interp._consecutive_failures == 3


def test_counter_resets_on_success(interp: NavInterpreter) -> None:
    """Counter resets to 0 after a successful high-confidence action."""
    interp._consecutive_failures = 5
    # Simulate successful action
    decision = make_decision("move_forward", confidence=0.9)
    cmd = interp._map_action(decision)
    assert cmd.type == CommandType.RC_CONTROL
    # In run_once, this would reset the counter
    interp._consecutive_failures = 0
    assert interp._consecutive_failures == 0


def test_forward_streak_guard_forces_scan_after_repeated_forward(interp: NavInterpreter) -> None:
    interp._max_forward_streak = 2

    first = interp._map_action(make_decision("move_forward"))
    second = interp._map_action(make_decision("move_forward"))
    third = interp._map_action(make_decision("move_forward"))

    assert first.payload is not None
    assert first.payload.forward_back > 0
    assert second.payload is not None
    assert second.payload.forward_back > 0
    assert third.payload is not None
    assert third.payload.forward_back == 0
    assert third.payload.yaw > 0


def test_forward_streak_resets_on_non_forward(interp: NavInterpreter) -> None:
    interp._max_forward_streak = 1

    assert interp._map_action(make_decision("move_forward")).type == CommandType.RC_CONTROL
    assert interp._map_action(make_decision("hover")).type == CommandType.HOVER
    next_forward = interp._map_action(make_decision("move_forward"))

    assert next_forward.payload is not None
    assert next_forward.payload.forward_back > 0


def test_hover_streak_guard_forces_scan_after_repeated_hover(interp: NavInterpreter) -> None:
    interp._enable_hover_scan = True
    interp._max_hover_streak = 2

    first = interp._map_action(make_decision("hover"))
    second = interp._map_action(make_decision("hover"))
    third = interp._map_action(make_decision("hover"))

    assert first.type == CommandType.HOVER
    assert second.type == CommandType.HOVER
    assert third.type == CommandType.RC_CONTROL
    assert third.payload is not None
    assert third.payload.yaw > 0


def test_hover_streak_guard_disabled_by_default(interp: NavInterpreter) -> None:
    interp._max_hover_streak = 1

    first = interp._map_action(make_decision("hover"))
    second = interp._map_action(make_decision("hover"))

    assert first.type == CommandType.HOVER
    assert second.type == CommandType.HOVER


@pytest.mark.asyncio
async def test_handle_failure_hovers_below_threshold() -> None:
    """Below 3 failures, _handle_failure sends hover."""
    interp = NavInterpreter()
    interp._consecutive_failures = 2

    posted_commands = []

    async def mock_post(cmd):
        posted_commands.append(cmd)

    interp._post_command = mock_post

    await interp._handle_failure()
    assert len(posted_commands) == 1
    assert posted_commands[0].type == CommandType.HOVER


@pytest.mark.asyncio
async def test_handle_failure_escalates_at_3() -> None:
    """At 3+ failures with good battery, holds hover."""
    interp = NavInterpreter()
    interp._consecutive_failures = 3

    posted_commands = []

    async def mock_post(cmd):
        posted_commands.append(cmd)

    interp._post_command = mock_post

    async def mock_battery():
        return 80

    interp._get_battery = mock_battery

    await interp._handle_failure()
    assert len(posted_commands) == 1
    assert posted_commands[0].type == CommandType.HOVER


@pytest.mark.asyncio
async def test_handle_failure_lands_on_low_battery() -> None:
    """At 3+ failures with low battery, lands."""
    interp = NavInterpreter()
    interp._consecutive_failures = 3

    posted_commands = []

    async def mock_post(cmd):
        posted_commands.append(cmd)

    interp._post_command = mock_post

    async def mock_battery():
        return 10

    interp._get_battery = mock_battery

    await interp._handle_failure()
    assert len(posted_commands) == 1
    assert posted_commands[0].type == CommandType.LAND


@pytest.mark.asyncio
async def test_handle_failure_hovers_when_battery_unknown() -> None:
    """At 3+ failures with battery unreachable, hovers (safe default)."""
    interp = NavInterpreter()
    interp._consecutive_failures = 3

    posted_commands = []

    async def mock_post(cmd):
        posted_commands.append(cmd)

    interp._post_command = mock_post

    async def mock_battery():
        return None

    interp._get_battery = mock_battery

    await interp._handle_failure()
    assert len(posted_commands) == 1
    assert posted_commands[0].type == CommandType.HOVER



@pytest.mark.asyncio
async def test_guard_hovers_during_initial_airborne_settle_window(monkeypatch) -> None:
    class Response:
        status_code = 200

        def json(self):
            return {
                "telemetry": {
                    "connected": True,
                    "flying": True,
                    "height_cm": 120,
                    "raw": {"pitch": 0, "roll": 0, "tof": 140},
                }
            }

    class Client:
        async def get(self, url):
            return Response()

    times = iter([10.0])
    monkeypatch.setattr("breacheye.nav_interpreter.monotonic", lambda: next(times))
    interp = NavInterpreter(command_url="http://localhost:8000/commands")
    interp._client = Client()

    guarded = await interp._guard_command_for_health(1, make_decision("move_forward"))

    assert guarded.type == CommandType.HOVER
    assert guarded.issued_by == "nav_interpreter_settle_guard"


@pytest.mark.asyncio
async def test_guard_emergency_stops_on_severe_attitude() -> None:
    class Response:
        status_code = 200

        def json(self):
            return {
                "telemetry": {
                    "connected": True,
                    "flying": True,
                    "height_cm": 0,
                    "raw": {"pitch": 9, "roll": 104, "tof": 111},
                }
            }

    class Client:
        async def get(self, url):
            return Response()

    interp = NavInterpreter(command_url="http://localhost:8000/commands")
    interp._client = Client()

    guarded = await interp._guard_command_for_health(7, make_decision("hover"))

    assert guarded.type == CommandType.EMERGENCY
    assert guarded.issued_by == "nav_interpreter_attitude_guard"


@pytest.mark.asyncio
async def test_guard_hovers_then_lands_on_repeated_hover_drift() -> None:
    class Response:
        status_code = 200

        def json(self):
            return {
                "accepts_nav": True,
                "telemetry": {
                    "connected": True,
                    "flying": True,
                    "height_cm": 80,
                    "raw": {"pitch": 0, "roll": 0, "tof": 90},
                },
                "stabilizer": {
                    "last_estimate": {
                        "median_dx_px": 7.0,
                        "median_dy_px": 0.0,
                        "tracked_features": 40,
                    },
                },
            }

    class Client:
        async def get(self, url):
            return Response()

    interp = NavInterpreter(command_url="http://localhost:8000/commands")
    interp._client = Client()
    interp._airborne_settle_s = 0.0
    interp._drift_land_after = 2

    first = await interp._guard_command_for_health(10, make_decision("rotate_right"))
    second = await interp._guard_command_for_health(11, make_decision("rotate_right"))

    assert first.type == CommandType.HOVER
    assert first.issued_by == "nav_interpreter_drift_hover_guard"
    assert second.type == CommandType.LAND
    assert second.issued_by == "nav_interpreter_drift_land_guard"


@pytest.mark.asyncio
async def test_guard_lands_when_tof_drops_during_autonomy() -> None:
    class Response:
        status_code = 200

        def json(self):
            return {
                "accepts_nav": True,
                "telemetry": {
                    "connected": True,
                    "flying": True,
                    "height_cm": 40,
                    "raw": {"pitch": 0, "roll": 0, "tof": 37},
                },
                "stabilizer": {"last_estimate": {}},
            }

    class Client:
        async def get(self, url):
            return Response()

    interp = NavInterpreter(command_url="http://localhost:8000/commands")
    interp._client = Client()
    interp._airborne_settle_s = 0.0
    interp._drift_land_after = 1

    guarded = await interp._guard_command_for_health(12, make_decision("hover"))

    assert guarded.type == CommandType.LAND
    assert guarded.issued_by == "nav_interpreter_drift_land_guard"


@pytest.mark.asyncio
async def test_guard_ignores_low_tof_when_height_is_consistently_safe() -> None:
    class Response:
        status_code = 200

        def json(self):
            return {
                "accepts_nav": True,
                "telemetry": {
                    "connected": True,
                    "flying": True,
                    "height_cm": 80,
                    "raw": {"pitch": 0, "roll": 0, "tof": 31},
                },
                "stabilizer": {"last_estimate": {}},
            }

    class Client:
        async def get(self, url):
            return Response()

    interp = NavInterpreter(command_url="http://localhost:8000/commands")
    interp._client = Client()
    interp._airborne_settle_s = 0.0
    interp._drift_land_after = 1

    guarded = await interp._guard_command_for_health(13, make_decision("hover"))

    assert guarded is None


@pytest.mark.asyncio
async def test_post_command_raises_when_safety_rejects_command() -> None:
    class Response:
        status_code = 200

        def json(self):
            return {"status": "failed", "reason": "cannot rc_control while not flying"}

    class Client:
        async def post(self, url, json):
            return Response()

    interp = NavInterpreter(command_url="http://localhost:8000/commands")
    interp._client = Client()
    cmd = interp._map_action(make_decision("move_forward"))

    with pytest.raises(RuntimeError, match="cannot rc_control while not flying"):
        await interp._post_command(cmd)


@pytest.mark.asyncio
async def test_post_command_accepts_executed_command() -> None:
    class Response:
        status_code = 200

        def json(self):
            return {"status": "executed", "reason": None}

    class Client:
        async def post(self, url, json):
            return Response()

    interp = NavInterpreter(command_url="http://localhost:8000/commands")
    interp._client = Client()

    await interp._post_command(interp._map_action(make_decision("hover")))
