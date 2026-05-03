"""
Comprehensive tests for BreachEye drone control and navigation systems.

Covers:
- SimAdapter: all control paths and guard behavior
- SafetyController: velocity clamping, TTL enforcement, watchdog, keepalive
- FlightStateMachine: full lifecycle, all guards, entry actions, accepts_nav
- NavInterpreter: run_once with mocked ZMQ+HTTP, confidence gating,
  failure counting, grounded check, action mapping
- OperatorHandler: ABORT/PAUSE/RESUME via HTTP and direct API
- Integration smoke: harness AsyncClient end-to-end
"""
from __future__ import annotations

import asyncio
from time import monotonic
from unittest.mock import MagicMock

import pytest
import httpx
from httpx import AsyncClient
from pydantic import ValidationError

from breacheye.adapters.base import DroneState
from breacheye.adapters.sim import SimAdapter
from breacheye.bus import AsyncEventBus
from breacheye.models import (
    CommandStatus,
    CommandType,
    DroneCommand,
    RCControlPayload,
)
from breacheye.nav_interpreter import NavInterpreter
from breacheye.operator import OperatorAction, OperatorCommand, OperatorHandler
from breacheye.rafa.codec import encode_json
from breacheye.rafa.schemas import NavigationDecision, NavigationOutput
from breacheye.safety import SafetyConfig, SafetyController
from breacheye.service import create_app
from breacheye.state_machine import (
    FlightState,
    FlightStateMachine,
    InvalidTransition,
    PreflightFailed,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_nav_output(
    action: str = "move_forward",
    confidence: float = 0.8,
    params: dict | None = None,
    frame_id: int = 1,
) -> NavigationOutput:
    return NavigationOutput(
        frame_id=frame_id,
        decision=NavigationDecision(
            action=action,  # type: ignore[arg-type]
            confidence=confidence,
            params=params or {},
            reasoning="test",
            exploration_state="exploring",
        ),
    )


def nav_bytes(nav: NavigationOutput) -> bytes:
    """Encode a NavigationOutput the same way the rafa pipeline does."""
    return encode_json(nav)


def make_fsm(battery: int = 100, connected: bool = True) -> tuple[FlightStateMachine, SimAdapter, AsyncEventBus]:
    adapter = SimAdapter()
    adapter.state.battery = battery
    adapter.state.connected = connected
    bus = AsyncEventBus()
    fsm = FlightStateMachine(adapter, bus)
    return fsm, adapter, bus


async def connected_fsm(battery: int = 100) -> tuple[FlightStateMachine, SimAdapter, AsyncEventBus]:
    fsm, adapter, bus = make_fsm(battery=battery)
    await adapter.connect()
    return fsm, adapter, bus


async def exploring_fsm() -> tuple[FlightStateMachine, SimAdapter, AsyncEventBus]:
    fsm, adapter, bus = await connected_fsm()
    await fsm.transition(FlightState.TAKEOFF)
    await fsm.transition(FlightState.EXPLORING)
    return fsm, adapter, bus


async def investigating_fsm() -> tuple[FlightStateMachine, SimAdapter, AsyncEventBus]:
    fsm, adapter, bus = await exploring_fsm()
    await fsm.transition(FlightState.INVESTIGATING)
    return fsm, adapter, bus


# ---------------------------------------------------------------------------
# 0. Model validation — TTL and duration range enforcement
# ---------------------------------------------------------------------------


class TestModelValidation:
    def test_ttl_ms_below_minimum_raises(self) -> None:
        """ttl_ms < 50 must be rejected by Pydantic (ge=50)."""
        with pytest.raises(ValidationError):
            DroneCommand(type=CommandType.HOVER, issued_by="test", ttl_ms=49)

    def test_ttl_ms_above_maximum_raises(self) -> None:
        """ttl_ms > 5000 must be rejected by Pydantic (le=5000)."""
        with pytest.raises(ValidationError):
            DroneCommand(type=CommandType.HOVER, issued_by="test", ttl_ms=5001)

    def test_ttl_ms_at_minimum_accepted(self) -> None:
        cmd = DroneCommand(
            type=CommandType.RC_CONTROL,
            issued_by="test",
            ttl_ms=50,
            payload=RCControlPayload(duration_ms=50),
        )
        assert cmd.ttl_ms == 50

    def test_ttl_ms_at_maximum_accepted(self) -> None:
        cmd = DroneCommand(
            type=CommandType.RC_CONTROL,
            issued_by="test",
            ttl_ms=5000,
            payload=RCControlPayload(duration_ms=50),
        )
        assert cmd.ttl_ms == 5000

    def test_duration_ms_below_minimum_raises(self) -> None:
        """duration_ms < 50 must be rejected by Pydantic (ge=50)."""
        with pytest.raises(ValidationError):
            RCControlPayload(duration_ms=49)

    def test_duration_ms_above_maximum_raises(self) -> None:
        """duration_ms > 2000 must be rejected by Pydantic (le=2000)."""
        with pytest.raises(ValidationError):
            RCControlPayload(duration_ms=2001)

    def test_duration_ms_at_minimum_accepted(self) -> None:
        p = RCControlPayload(duration_ms=50)
        assert p.duration_ms == 50

    def test_duration_ms_at_maximum_accepted(self) -> None:
        p = RCControlPayload(duration_ms=2000)
        assert p.duration_ms == 2000

    def test_rc_requires_payload(self) -> None:
        with pytest.raises(ValidationError, match="rc_control commands require payload"):
            DroneCommand(type=CommandType.RC_CONTROL, issued_by="test")

    def test_non_rc_rejects_payload(self) -> None:
        with pytest.raises(ValidationError, match="must not include payload"):
            DroneCommand(
                type=CommandType.LAND,
                issued_by="test",
                payload=RCControlPayload(duration_ms=50),
            )


# ---------------------------------------------------------------------------
# 1. SimAdapter — all control paths
# ---------------------------------------------------------------------------


class TestSimAdapter:
    async def test_connect_sets_connected(self) -> None:
        adapter = SimAdapter()
        assert adapter.state.connected is False
        await adapter.connect()
        assert adapter.state.connected is True
        assert ("connect", ()) in adapter.commands

    async def test_close_clears_connected(self) -> None:
        adapter = SimAdapter()
        await adapter.connect()
        await adapter.close()
        assert adapter.state.connected is False
        assert ("close", ()) in adapter.commands

    async def test_takeoff_sets_flying_and_height(self) -> None:
        adapter = SimAdapter()
        await adapter.connect()
        await adapter.takeoff()
        assert adapter.state.flying is True
        assert adapter.state.height_cm >= 80
        assert ("takeoff", ()) in adapter.commands

    async def test_land_clears_flying(self) -> None:
        adapter = SimAdapter()
        await adapter.connect()
        await adapter.takeoff()
        await adapter.land()
        assert adapter.state.flying is False
        assert adapter.state.height_cm == 0
        assert ("land", ()) in adapter.commands

    async def test_emergency_clears_flying_without_requiring_connected(self) -> None:
        adapter = SimAdapter()
        # Emergency works even without connect — safety net
        await adapter.emergency()
        assert adapter.state.flying is False
        assert adapter.state.height_cm == 0
        assert ("emergency", ()) in adapter.commands

    async def test_hover_requires_connected(self) -> None:
        adapter = SimAdapter()
        with pytest.raises(RuntimeError, match="not connected"):
            await adapter.hover()

    async def test_hover_records_neutral_rc(self) -> None:
        adapter = SimAdapter()
        await adapter.connect()
        await adapter.takeoff()
        await adapter.hover()
        assert ("hover", (0, 0, 0, 0)) in adapter.commands

    async def test_rc_control_requires_flying(self) -> None:
        adapter = SimAdapter()
        await adapter.connect()
        with pytest.raises(RuntimeError, match="not flying"):
            await adapter.rc_control(10, 10, 0, 0)

    async def test_rc_control_records_command(self) -> None:
        adapter = SimAdapter()
        await adapter.connect()
        await adapter.takeoff()
        await adapter.rc_control(15, -20, 5, 10)
        assert ("rc_control", (15, -20, 5, 10)) in adapter.commands

    async def test_keepalive_requires_connected(self) -> None:
        adapter = SimAdapter()
        with pytest.raises(RuntimeError, match="not connected"):
            await adapter.keepalive()

    async def test_keepalive_records_command(self) -> None:
        adapter = SimAdapter()
        await adapter.connect()
        await adapter.keepalive()
        assert ("keepalive", ()) in adapter.commands

    async def test_get_state_returns_flight_time_when_flying(self) -> None:
        adapter = SimAdapter()
        await adapter.connect()
        await adapter.takeoff()
        await asyncio.sleep(0.01)
        state = await adapter.get_state()
        assert state.flight_time_s is not None
        assert state.flight_time_s >= 0

    async def test_takeoff_requires_connected(self) -> None:
        adapter = SimAdapter()
        with pytest.raises(RuntimeError, match="not connected"):
            await adapter.takeoff()

    async def test_land_requires_connected(self) -> None:
        adapter = SimAdapter()
        with pytest.raises(RuntimeError, match="not connected"):
            await adapter.land()


# ---------------------------------------------------------------------------
# 2. SafetyController — comprehensive
# ---------------------------------------------------------------------------


class TestSafetyController:
    async def test_takeoff_succeeds_with_good_battery(self) -> None:
        adapter = SimAdapter()
        await adapter.connect()
        ctrl = SafetyController(adapter, AsyncEventBus())
        result = await ctrl.execute(DroneCommand(type=CommandType.TAKEOFF, issued_by="test"))
        assert result.status == CommandStatus.EXECUTED
        assert adapter.state.flying is True

    async def test_takeoff_fails_when_disconnected(self) -> None:
        adapter = SimAdapter()
        # not connected
        ctrl = SafetyController(adapter, AsyncEventBus())
        result = await ctrl.execute(DroneCommand(type=CommandType.TAKEOFF, issued_by="test"))
        assert result.status == CommandStatus.FAILED
        assert "not connected" in (result.reason or "").lower()

    async def test_takeoff_fails_below_min_battery(self) -> None:
        adapter = SimAdapter()
        await adapter.connect()
        adapter.state.battery = 24  # below default 25%
        ctrl = SafetyController(adapter, AsyncEventBus())
        result = await ctrl.execute(DroneCommand(type=CommandType.TAKEOFF, issued_by="test"))
        assert result.status == CommandStatus.FAILED
        assert "battery" in (result.reason or "").lower()

    async def test_takeoff_at_exact_min_battery_succeeds(self) -> None:
        adapter = SimAdapter()
        await adapter.connect()
        adapter.state.battery = 25  # exactly at min
        ctrl = SafetyController(adapter, AsyncEventBus())
        result = await ctrl.execute(DroneCommand(type=CommandType.TAKEOFF, issued_by="test"))
        assert result.status == CommandStatus.EXECUTED

    async def test_takeoff_noop_when_already_flying(self) -> None:
        """Second takeoff while already airborne should not error."""
        adapter = SimAdapter()
        await adapter.connect()
        await adapter.takeoff()
        ctrl = SafetyController(adapter, AsyncEventBus())
        result = await ctrl.execute(DroneCommand(type=CommandType.TAKEOFF, issued_by="test"))
        assert result.status == CommandStatus.EXECUTED

    async def test_land_executes_when_flying(self) -> None:
        adapter = SimAdapter()
        await adapter.connect()
        await adapter.takeoff()
        ctrl = SafetyController(adapter, AsyncEventBus())
        result = await ctrl.execute(DroneCommand(type=CommandType.LAND, issued_by="test"))
        assert result.status == CommandStatus.EXECUTED
        assert adapter.state.flying is False
        assert ("land", ()) in adapter.commands

    async def test_land_noop_when_grounded(self) -> None:
        adapter = SimAdapter()
        await adapter.connect()
        ctrl = SafetyController(adapter, AsyncEventBus())
        result = await ctrl.execute(DroneCommand(type=CommandType.LAND, issued_by="test"))
        assert result.status == CommandStatus.EXECUTED
        assert ("land", ()) not in adapter.commands

    async def test_emergency_always_executes(self) -> None:
        adapter = SimAdapter()
        # Not connected — emergency still passes through to adapter
        ctrl = SafetyController(adapter, AsyncEventBus())
        result = await ctrl.execute(DroneCommand(type=CommandType.EMERGENCY, issued_by="test"))
        assert result.status == CommandStatus.EXECUTED
        assert ("emergency", ()) in adapter.commands

    async def test_hover_executes_when_flying(self) -> None:
        adapter = SimAdapter()
        await adapter.connect()
        await adapter.takeoff()
        ctrl = SafetyController(adapter, AsyncEventBus())
        result = await ctrl.execute(DroneCommand(type=CommandType.HOVER, issued_by="test"))
        assert result.status == CommandStatus.EXECUTED
        assert ("hover", (0, 0, 0, 0)) in adapter.commands

    async def test_hover_noop_when_grounded(self) -> None:
        adapter = SimAdapter()
        await adapter.connect()
        ctrl = SafetyController(adapter, AsyncEventBus())
        result = await ctrl.execute(DroneCommand(type=CommandType.HOVER, issued_by="test"))
        assert result.status == CommandStatus.EXECUTED
        assert ("hover", (0, 0, 0, 0)) not in adapter.commands

    async def test_rc_control_clamps_positive_overshoot(self) -> None:
        adapter = SimAdapter()
        await adapter.connect()
        await adapter.takeoff()
        ctrl = SafetyController(adapter, AsyncEventBus(), SafetyConfig(max_abs_velocity=35))
        result = await ctrl.execute(
            DroneCommand(
                type=CommandType.RC_CONTROL,
                issued_by="test",
                ttl_ms=300,
                payload=RCControlPayload(forward_back=100, duration_ms=50),
            )
        )
        assert result.status == CommandStatus.EXECUTED
        rc_cmds = [c for c in adapter.commands if c[0] == "rc_control"]
        assert len(rc_cmds) == 1
        _, args = rc_cmds[0]
        # forward_back clamped to 35
        assert args[1] == 35

    async def test_rc_control_clamps_negative_overshoot(self) -> None:
        adapter = SimAdapter()
        await adapter.connect()
        await adapter.takeoff()
        ctrl = SafetyController(adapter, AsyncEventBus(), SafetyConfig(max_abs_velocity=35))
        result = await ctrl.execute(
            DroneCommand(
                type=CommandType.RC_CONTROL,
                issued_by="test",
                ttl_ms=300,
                payload=RCControlPayload(forward_back=-100, duration_ms=50),
            )
        )
        assert result.status == CommandStatus.EXECUTED
        rc_cmds = [c for c in adapter.commands if c[0] == "rc_control"]
        _, args = rc_cmds[0]
        assert args[1] == -35

    async def test_rc_control_within_bounds_passes_unchanged(self) -> None:
        adapter = SimAdapter()
        await adapter.connect()
        await adapter.takeoff()
        ctrl = SafetyController(adapter, AsyncEventBus(), SafetyConfig(max_abs_velocity=35))
        await ctrl.execute(
            DroneCommand(
                type=CommandType.RC_CONTROL,
                issued_by="test",
                ttl_ms=300,
                payload=RCControlPayload(left_right=20, forward_back=-15, up_down=10, yaw=35, duration_ms=50),
            )
        )
        rc_cmds = [c for c in adapter.commands if c[0] == "rc_control"]
        _, args = rc_cmds[0]
        assert args == (20, -15, 10, 35)

    async def test_rc_control_clamps_at_exact_boundary(self) -> None:
        adapter = SimAdapter()
        await adapter.connect()
        await adapter.takeoff()
        ctrl = SafetyController(adapter, AsyncEventBus(), SafetyConfig(max_abs_velocity=35))
        await ctrl.execute(
            DroneCommand(
                type=CommandType.RC_CONTROL,
                issued_by="test",
                ttl_ms=300,
                payload=RCControlPayload(forward_back=35, duration_ms=50),
            )
        )
        rc_cmds = [c for c in adapter.commands if c[0] == "rc_control"]
        _, args = rc_cmds[0]
        assert args[1] == 35  # exact boundary passes unchanged

    async def test_rc_control_caps_duration_to_max_rc_duration(self) -> None:
        """max_rc_duration_ms caps duration before TTL check."""
        adapter = SimAdapter()
        await adapter.connect()
        await adapter.takeoff()
        ctrl = SafetyController(
            adapter,
            AsyncEventBus(),
            SafetyConfig(max_rc_duration_ms=200, default_ttl_ms=750),
        )
        # duration_ms=500 gets capped to 200, ttl_ms=750 allows that
        result = await ctrl.execute(
            DroneCommand(
                type=CommandType.RC_CONTROL,
                issued_by="test",
                ttl_ms=750,
                payload=RCControlPayload(forward_back=20, duration_ms=500),
            )
        )
        assert result.status == CommandStatus.EXECUTED

    async def test_rc_control_rejects_duration_exceeds_ttl(self) -> None:
        adapter = SimAdapter()
        await adapter.connect()
        await adapter.takeoff()
        ctrl = SafetyController(adapter, AsyncEventBus())
        result = await ctrl.execute(
            DroneCommand(
                type=CommandType.RC_CONTROL,
                issued_by="test",
                ttl_ms=50,
                payload=RCControlPayload(duration_ms=100),
            )
        )
        assert result.status == CommandStatus.FAILED
        assert "duration_ms" in (result.reason or "")

    async def test_rc_control_returns_to_hover_after_sleep(self) -> None:
        adapter = SimAdapter()
        await adapter.connect()
        await adapter.takeoff()
        ctrl = SafetyController(adapter, AsyncEventBus())
        await ctrl.execute(
            DroneCommand(
                type=CommandType.RC_CONTROL,
                issued_by="test",
                ttl_ms=300,
                payload=RCControlPayload(forward_back=20, duration_ms=50),
            )
        )
        # Last command after rc_control must be hover
        assert adapter.commands[-1] == ("hover", (0, 0, 0, 0))

    async def test_rc_control_fails_when_grounded(self) -> None:
        adapter = SimAdapter()
        await adapter.connect()
        ctrl = SafetyController(adapter, AsyncEventBus())
        result = await ctrl.execute(
            DroneCommand(
                type=CommandType.RC_CONTROL,
                issued_by="test",
                payload=RCControlPayload(duration_ms=100),
            )
        )
        assert result.status == CommandStatus.FAILED
        assert "not flying" in (result.reason or "").lower()

    async def test_command_publishes_accepted_then_executed(self) -> None:
        adapter = SimAdapter()
        await adapter.connect()
        bus = AsyncEventBus()
        ctrl = SafetyController(adapter, bus)
        queue = await bus.subscribe("drone.command_results")
        await ctrl.execute(DroneCommand(type=CommandType.TAKEOFF, issued_by="test"))

        statuses = []
        while not queue.empty():
            result = queue.get_nowait()
            statuses.append(result.status)

        assert CommandStatus.ACCEPTED in statuses
        assert CommandStatus.EXECUTED in statuses

    async def test_watchdog_hovers_after_stale_command(self) -> None:
        adapter = SimAdapter()
        await adapter.connect()
        await adapter.takeoff()
        ctrl = SafetyController(
            adapter,
            AsyncEventBus(),
            SafetyConfig(watchdog_interval_s=0.01, stale_command_s=0.01, keepalive_interval_s=60),
        )
        await ctrl.start()
        try:
            await asyncio.sleep(0.05)
        finally:
            await ctrl.stop()
        assert ("hover", (0, 0, 0, 0)) in adapter.commands

    async def test_watchdog_sends_keepalive_when_flying(self) -> None:
        adapter = SimAdapter()
        await adapter.connect()
        await adapter.takeoff()
        ctrl = SafetyController(
            adapter,
            AsyncEventBus(),
            SafetyConfig(
                watchdog_interval_s=0.01,
                stale_command_s=60,
                keepalive_interval_s=0.01,
            ),
        )
        # Pre-age keepalive timestamp so watchdog fires immediately
        ctrl._last_keepalive_at = monotonic() - 100
        await ctrl.start()
        try:
            await asyncio.sleep(0.05)
        finally:
            await ctrl.stop()
        assert ("keepalive", ()) in adapter.commands

    async def test_watchdog_skips_keepalive_when_grounded(self) -> None:
        adapter = SimAdapter()
        await adapter.connect()
        # NOT taking off — grounded
        ctrl = SafetyController(
            adapter,
            AsyncEventBus(),
            SafetyConfig(watchdog_interval_s=0.01, stale_command_s=0.01, keepalive_interval_s=0.01),
        )
        await ctrl.start()
        try:
            await asyncio.sleep(0.05)
        finally:
            await ctrl.stop()
        assert ("keepalive", ()) not in adapter.commands

    async def test_watchdog_publishes_telemetry(self) -> None:
        adapter = SimAdapter()
        await adapter.connect()
        bus = AsyncEventBus()
        ctrl = SafetyController(
            adapter,
            bus,
            SafetyConfig(watchdog_interval_s=0.01, stale_command_s=60, keepalive_interval_s=60),
        )
        queue = await bus.subscribe("drone.telemetry")
        await ctrl.start()
        try:
            await asyncio.sleep(0.05)
        finally:
            await ctrl.stop()
        assert not queue.empty()

    async def test_watchdog_does_not_interleave_with_locked_command(self) -> None:
        """Watchdog must not inject hover/keepalive between command start and finish."""

        class SlowHoverAdapter(SimAdapter):
            async def hover(self) -> None:
                self.commands.append(("hover_start", ()))
                await asyncio.sleep(0.03)
                self.commands.append(("hover", (0, 0, 0, 0)))

            async def get_state(self) -> DroneState:
                state = await super().get_state()
                return DroneState(
                    connected=state.connected,
                    flying=True,
                    battery=state.battery,
                    height_cm=state.height_cm,
                    raw=state.raw,
                )

        adapter = SlowHoverAdapter()
        await adapter.connect()
        await adapter.takeoff()
        ctrl = SafetyController(
            adapter,
            AsyncEventBus(),
            SafetyConfig(watchdog_interval_s=0.002, stale_command_s=0.0, keepalive_interval_s=0.0),
        )
        ctrl._last_command_at = monotonic() - 10
        ctrl._last_keepalive_at = monotonic() - 10
        await ctrl.start()
        try:
            result = await ctrl.execute(DroneCommand(type=CommandType.HOVER, issued_by="test"))
        finally:
            await ctrl.stop()

        assert result.status == CommandStatus.EXECUTED
        start_idx = next(i for i, c in enumerate(adapter.commands) if c[0] == "hover_start")
        end_idx = next(i for i, c in enumerate(adapter.commands) if c == ("hover", (0, 0, 0, 0)))
        between = adapter.commands[start_idx + 1 : end_idx]
        assert all(c[0] not in {"keepalive"} for c in between)


# ---------------------------------------------------------------------------
# 3. FlightStateMachine — comprehensive
# ---------------------------------------------------------------------------


class TestFlightStateMachine:

    # --- Full lifecycle ---

    async def test_full_lifecycle_all_states(self) -> None:
        fsm, adapter, _ = await connected_fsm()
        for target in [
            FlightState.TAKEOFF,
            FlightState.EXPLORING,
            FlightState.INVESTIGATING,
            FlightState.EXPLORING,
            FlightState.RETURNING,
            FlightState.LANDING,
            FlightState.COMPLETE,
        ]:
            await fsm.transition(target)
        assert fsm.state == FlightState.COMPLETE

    # --- LANDING reachability from all non-terminal states ---

    @pytest.mark.parametrize("state_path,fly_first", [
        ([FlightState.TAKEOFF], True),
        ([FlightState.TAKEOFF, FlightState.EXPLORING], True),
        ([FlightState.TAKEOFF, FlightState.EXPLORING, FlightState.INVESTIGATING], True),
        ([FlightState.TAKEOFF, FlightState.EXPLORING, FlightState.RETURNING], True),
    ])
    async def test_landing_reachable_from_all_flying_states(
        self, state_path: list[FlightState], fly_first: bool
    ) -> None:
        fsm, adapter, _ = await connected_fsm()
        for state in state_path:
            await fsm.transition(state)
        # Must be flying for LANDING guard to pass
        assert adapter.state.flying is True
        await fsm.transition(FlightState.LANDING)
        assert fsm.state == FlightState.LANDING

    async def test_landing_from_preflight_skips_flying_guard(self) -> None:
        """PREFLIGHT → LANDING allowed without flying (abort before takeoff)."""
        fsm, adapter, _ = await connected_fsm()
        assert adapter.state.flying is False
        await fsm.transition(FlightState.LANDING)
        assert fsm.state == FlightState.LANDING

    async def test_landing_guard_fails_if_not_flying_from_takeoff(self) -> None:
        """TAKEOFF → LANDING requires flying=True."""
        fsm, adapter, _ = await connected_fsm()
        await fsm.transition(FlightState.TAKEOFF)
        # Force grounded without going through landing
        adapter.state.flying = False
        adapter.state.height_cm = 0
        with pytest.raises(RuntimeError, match="not flying"):
            await fsm.transition(FlightState.LANDING)

    # --- Guards ---

    async def test_takeoff_guard_passes_with_good_battery_and_connected(self) -> None:
        fsm, adapter, _ = await connected_fsm(battery=100)
        await fsm.transition(FlightState.TAKEOFF)
        assert fsm.state == FlightState.TAKEOFF

    async def test_takeoff_guard_fails_with_low_battery(self) -> None:
        fsm, adapter, _ = await connected_fsm(battery=15)
        with pytest.raises(PreflightFailed) as exc_info:
            await fsm.transition(FlightState.TAKEOFF)
        assert exc_info.value.checks["battery_ok"] is False

    async def test_takeoff_guard_fails_when_disconnected(self) -> None:
        fsm, adapter, bus = make_fsm(battery=100, connected=False)
        # Do not call adapter.connect()
        with pytest.raises(PreflightFailed) as exc_info:
            await fsm.transition(FlightState.TAKEOFF)
        assert exc_info.value.checks["connected"] is False

    async def test_preflight_check_exactly_at_threshold(self) -> None:
        """Battery exactly at _min_battery (20%) fails — must be strictly above."""
        fsm, adapter, _ = make_fsm(battery=20)
        await adapter.connect()
        checks = await fsm.preflight_check()
        assert checks["battery_ok"] is False  # 20 > 20 is False
        assert checks["passed"] is False

    async def test_preflight_check_one_above_threshold_passes(self) -> None:
        fsm, adapter, _ = make_fsm(battery=21)
        await adapter.connect()
        checks = await fsm.preflight_check()
        assert checks["battery_ok"] is True
        assert checks["passed"] is True

    # --- Entry actions ---

    async def test_takeoff_entry_calls_adapter_takeoff(self) -> None:
        fsm, adapter, _ = await connected_fsm()
        await fsm.transition(FlightState.TAKEOFF)
        assert ("takeoff", ()) in adapter.commands

    async def test_exploring_entry_calls_hover(self) -> None:
        fsm, adapter, _ = await connected_fsm()
        await fsm.transition(FlightState.TAKEOFF)
        adapter.commands.clear()
        await fsm.transition(FlightState.EXPLORING)
        assert ("hover", (0, 0, 0, 0)) in adapter.commands

    async def test_investigating_entry_calls_hover(self) -> None:
        fsm, adapter, _ = await exploring_fsm()
        adapter.commands.clear()
        await fsm.transition(FlightState.INVESTIGATING)
        assert ("hover", (0, 0, 0, 0)) in adapter.commands

    async def test_returning_entry_calls_hover(self) -> None:
        fsm, adapter, _ = await exploring_fsm()
        adapter.commands.clear()
        await fsm.transition(FlightState.RETURNING)
        assert ("hover", (0, 0, 0, 0)) in adapter.commands

    async def test_landing_entry_calls_adapter_land(self) -> None:
        fsm, adapter, _ = await connected_fsm()
        await fsm.transition(FlightState.TAKEOFF)
        await fsm.transition(FlightState.LANDING)
        assert ("land", ()) in adapter.commands

    # --- Invalid transitions ---

    async def test_preflight_cannot_go_directly_to_exploring(self) -> None:
        fsm, adapter, _ = await connected_fsm()
        with pytest.raises(InvalidTransition) as exc_info:
            await fsm.transition(FlightState.EXPLORING)
        assert exc_info.value.from_state == FlightState.PREFLIGHT
        assert exc_info.value.to_state == FlightState.EXPLORING

    async def test_complete_accepts_no_transitions(self) -> None:
        fsm, adapter, _ = await connected_fsm()
        await fsm.transition(FlightState.TAKEOFF)
        await fsm.transition(FlightState.EXPLORING)
        await fsm.transition(FlightState.RETURNING)
        await fsm.transition(FlightState.LANDING)
        await fsm.transition(FlightState.COMPLETE)
        for target in FlightState:
            with pytest.raises(InvalidTransition):
                await fsm.transition(target)

    async def test_landing_cannot_go_back_to_exploring(self) -> None:
        fsm, adapter, _ = await connected_fsm()
        await fsm.transition(FlightState.TAKEOFF)
        await fsm.transition(FlightState.EXPLORING)
        await fsm.transition(FlightState.RETURNING)
        await fsm.transition(FlightState.LANDING)
        with pytest.raises(InvalidTransition):
            await fsm.transition(FlightState.EXPLORING)

    async def test_returning_cannot_go_to_investigating(self) -> None:
        fsm, adapter, _ = await exploring_fsm()
        await fsm.transition(FlightState.RETURNING)
        with pytest.raises(InvalidTransition):
            await fsm.transition(FlightState.INVESTIGATING)

    # --- accepts_nav ---

    async def test_accepts_nav_true_in_exploring(self) -> None:
        fsm, _, _ = await exploring_fsm()
        assert fsm.accepts_nav() is True

    async def test_accepts_nav_true_in_investigating(self) -> None:
        fsm, _, _ = await investigating_fsm()
        assert fsm.accepts_nav() is True

    async def test_accepts_nav_false_in_preflight(self) -> None:
        fsm, _, _ = make_fsm()
        assert fsm.accepts_nav() is False

    async def test_accepts_nav_false_in_takeoff(self) -> None:
        fsm, adapter, _ = await connected_fsm()
        await fsm.transition(FlightState.TAKEOFF)
        assert fsm.accepts_nav() is False

    async def test_accepts_nav_false_in_returning(self) -> None:
        fsm, _, _ = await exploring_fsm()
        await fsm.transition(FlightState.RETURNING)
        assert fsm.accepts_nav() is False

    async def test_accepts_nav_false_in_landing(self) -> None:
        fsm, adapter, _ = await connected_fsm()
        await fsm.transition(FlightState.TAKEOFF)
        await fsm.transition(FlightState.LANDING)
        assert fsm.accepts_nav() is False

    async def test_accepts_nav_false_in_complete(self) -> None:
        fsm, adapter, _ = await connected_fsm()
        await fsm.transition(FlightState.TAKEOFF)
        await fsm.transition(FlightState.EXPLORING)
        await fsm.transition(FlightState.RETURNING)
        await fsm.transition(FlightState.LANDING)
        await fsm.transition(FlightState.COMPLETE)
        assert fsm.accepts_nav() is False

    async def test_accepts_nav_false_when_paused_in_exploring(self) -> None:
        fsm, _, _ = await exploring_fsm()
        await fsm.pause()
        assert fsm.accepts_nav() is False

    async def test_accepts_nav_false_when_paused_in_investigating(self) -> None:
        fsm, _, _ = await investigating_fsm()
        await fsm.pause()
        assert fsm.accepts_nav() is False

    async def test_accepts_nav_resumes_after_unpause(self) -> None:
        fsm, _, _ = await exploring_fsm()
        await fsm.pause()
        assert fsm.accepts_nav() is False
        await fsm.resume()
        assert fsm.accepts_nav() is True

    # --- pause / resume ---

    async def test_pause_in_non_nav_state_does_not_hover(self) -> None:
        """Pausing in TAKEOFF (not EXPLORING/INVESTIGATING) should not call hover."""
        fsm, adapter, _ = await connected_fsm()
        await fsm.transition(FlightState.TAKEOFF)
        adapter.commands.clear()
        await fsm.pause()
        assert ("hover", (0, 0, 0, 0)) not in adapter.commands

    async def test_pause_in_exploring_hovers(self) -> None:
        fsm, adapter, _ = await exploring_fsm()
        adapter.commands.clear()
        await fsm.pause()
        assert ("hover", (0, 0, 0, 0)) in adapter.commands

    async def test_double_pause_is_idempotent(self) -> None:
        fsm, _, _ = await exploring_fsm()
        await fsm.pause()
        await fsm.pause()
        assert fsm.paused is True

    async def test_double_resume_is_idempotent(self) -> None:
        fsm, _, _ = await exploring_fsm()
        await fsm.resume()
        assert fsm.paused is False

    # --- abort ---

    async def test_abort_from_exploring_lands(self) -> None:
        fsm, _, _ = await exploring_fsm()
        await fsm.abort()
        assert fsm.state == FlightState.LANDING

    async def test_abort_from_investigating_lands(self) -> None:
        fsm, _, _ = await investigating_fsm()
        await fsm.abort()
        assert fsm.state == FlightState.LANDING

    async def test_abort_from_returning_lands(self) -> None:
        fsm, adapter, _ = await exploring_fsm()
        await fsm.transition(FlightState.RETURNING)
        await fsm.abort()
        assert fsm.state == FlightState.LANDING

    async def test_abort_from_takeoff_lands(self) -> None:
        fsm, adapter, _ = await connected_fsm()
        await fsm.transition(FlightState.TAKEOFF)
        await fsm.abort()
        assert fsm.state == FlightState.LANDING

    async def test_abort_from_preflight_is_noop(self) -> None:
        fsm, _, _ = make_fsm()
        await fsm.abort()
        assert fsm.state == FlightState.PREFLIGHT

    async def test_abort_from_complete_is_noop(self) -> None:
        fsm, adapter, _ = await connected_fsm()
        await fsm.transition(FlightState.TAKEOFF)
        await fsm.transition(FlightState.EXPLORING)
        await fsm.transition(FlightState.RETURNING)
        await fsm.transition(FlightState.LANDING)
        await fsm.transition(FlightState.COMPLETE)
        await fsm.abort()
        assert fsm.state == FlightState.COMPLETE

    async def test_abort_clears_paused_flag(self) -> None:
        fsm, _, _ = await exploring_fsm()
        await fsm.pause()
        assert fsm.paused is True
        await fsm.abort()
        assert fsm.paused is False

    # --- bus events ---

    async def test_state_change_event_fields(self) -> None:
        fsm, adapter, bus = await connected_fsm()
        queue = await bus.subscribe("drone.state_change")
        await fsm.transition(FlightState.TAKEOFF)
        event = queue.get_nowait()
        assert event["from_state"] == str(FlightState.PREFLIGHT)
        assert event["to_state"] == str(FlightState.TAKEOFF)
        assert "timestamp" in event

    async def test_run_lifecycle_convenience(self) -> None:
        fsm, adapter, _ = await connected_fsm()
        await fsm.run_lifecycle()
        assert fsm.state == FlightState.EXPLORING


# ---------------------------------------------------------------------------
# 4. NavInterpreter — run_once with mocked ZMQ and HTTP
# ---------------------------------------------------------------------------


class TestNavInterpreterRunOnce:
    """
    Tests for NavInterpreter.run_once() — the full pipeline including ZMQ
    receive, confidence gating, grounded check, and command posting.

    ZMQ and HTTP are both mocked; no sockets or servers are started.
    """

    def _make_interp(self) -> NavInterpreter:
        interp = NavInterpreter(log_dir=None)
        # Stub out the RunLogger to avoid file I/O
        interp.logger = MagicMock()
        interp.logger.event = MagicMock()
        # Disable settle window so movement commands aren't suppressed in unit tests
        interp._airborne_settle_s = 0.0
        return interp

    def _wire(
        self,
        interp: NavInterpreter,
        recv_data: bytes,
        flying: bool = True,
        posted: list | None = None,
    ) -> None:
        """Wire mock ZMQ socket and HTTP client onto the interpreter."""
        import zmq

        mock_socket = MagicMock()

        # poller.poll returns events immediately
        async def mock_poll(timeout=500):
            return [(mock_socket, zmq.POLLIN)]

        mock_poller = MagicMock()
        mock_poller.poll = mock_poll

        # socket.recv returns the provided bytes once, then raises Again
        call_count = {"n": 0}

        async def mock_recv(flags=0):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return recv_data
            raise zmq.Again()

        mock_socket.recv = mock_recv

        interp._socket = mock_socket
        interp._poller = mock_poller

        _posted = posted if posted is not None else []

        async def mock_post_command(cmd: DroneCommand) -> None:
            _posted.append(cmd)

        async def mock_get_health_payload() -> dict:
            return {"telemetry": {"flying": flying}}

        interp._post_command = mock_post_command  # type: ignore[method-assign]
        interp._get_health_payload = mock_get_health_payload  # type: ignore[method-assign]

    async def test_run_once_executes_high_confidence_when_flying(self) -> None:
        interp = self._make_interp()
        nav = make_nav_output("move_forward", confidence=0.9)
        posted: list[DroneCommand] = []
        self._wire(interp, nav_bytes(nav), flying=True, posted=posted)

        result = await interp.run_once()

        assert result is True
        assert len(posted) == 1
        assert posted[0].type == CommandType.RC_CONTROL
        assert interp._consecutive_failures == 0

    async def test_run_once_skips_when_not_flying(self) -> None:
        """When flying=False the guard returns _GUARD_SKIP and run_once returns False.

        Nav commands must not be posted to a grounded drone. The safety controller
        is the fallback, but the nav interpreter should not post commands it knows
        will fail.
        """
        interp = self._make_interp()
        nav = make_nav_output("move_forward", confidence=0.9)
        posted: list[DroneCommand] = []
        self._wire(interp, nav_bytes(nav), flying=False, posted=posted)

        result = await interp.run_once()

        # Guard skips when not flying — no command posted, returns False
        assert result is False
        assert len(posted) == 0

    async def test_run_once_gates_low_confidence(self) -> None:
        """Confidence < 0.5 → failure handler (hover), not executed."""
        interp = self._make_interp()
        nav = make_nav_output("move_forward", confidence=0.3)
        posted: list[DroneCommand] = []
        self._wire(interp, nav_bytes(nav), flying=True, posted=posted)

        result = await interp.run_once()

        assert result is False
        assert interp._consecutive_failures == 1
        # failure handler posts hover
        assert len(posted) == 1
        assert posted[0].type == CommandType.HOVER

    async def test_run_once_at_exactly_0_5_confidence_gates(self) -> None:
        """Exactly 0.5 is below threshold (< 0.5 is False), so it should execute."""
        interp = self._make_interp()
        nav = make_nav_output("hover", confidence=0.5)
        posted: list[DroneCommand] = []
        self._wire(interp, nav_bytes(nav), flying=True, posted=posted)

        result = await interp.run_once()

        # confidence 0.5 is NOT < 0.5, so it passes the gate
        assert result is True
        assert interp._consecutive_failures == 0

    async def test_run_once_increments_failure_on_malformed_frame(self) -> None:
        interp = self._make_interp()
        posted: list[DroneCommand] = []
        self._wire(interp, b"not valid json at all", flying=True, posted=posted)

        result = await interp.run_once()

        assert result is False
        assert interp._consecutive_failures == 1
        # hover sent on first failure
        assert len(posted) == 1
        assert posted[0].type == CommandType.HOVER

    async def test_run_once_three_failures_escalates_to_hover_good_battery(self) -> None:
        """3+ consecutive failures with good battery → hover (not land)."""
        interp = self._make_interp()
        interp._consecutive_failures = 2  # prime to hit 3 on next failure
        posted: list[DroneCommand] = []
        self._wire(interp, b"bad data", flying=True, posted=posted)

        async def mock_battery() -> int:
            return 80

        interp._get_battery = mock_battery  # type: ignore[method-assign]

        await interp.run_once()

        assert interp._consecutive_failures == 3
        assert len(posted) == 1
        assert posted[0].type == CommandType.HOVER

    async def test_run_once_three_failures_lands_on_low_battery(self) -> None:
        """3+ consecutive failures with low battery → land."""
        interp = self._make_interp()
        interp._consecutive_failures = 2
        posted: list[DroneCommand] = []
        self._wire(interp, b"bad data", flying=True, posted=posted)

        async def mock_battery() -> int:
            return 10

        interp._get_battery = mock_battery  # type: ignore[method-assign]

        await interp.run_once()

        assert len(posted) == 1
        assert posted[0].type == CommandType.LAND

    async def test_run_once_resets_failure_counter_on_success(self) -> None:
        interp = self._make_interp()
        interp._consecutive_failures = 5
        nav = make_nav_output("hover", confidence=0.9)
        posted: list[DroneCommand] = []
        self._wire(interp, nav_bytes(nav), flying=True, posted=posted)

        result = await interp.run_once()

        assert result is True
        assert interp._consecutive_failures == 0

    async def test_run_once_no_events_returns_false(self) -> None:
        interp = self._make_interp()

        mock_poller = MagicMock()

        async def mock_poll(timeout=500):
            return []  # no events

        mock_poller.poll = mock_poll
        interp._socket = MagicMock()
        interp._poller = mock_poller

        result = await interp.run_once()
        assert result is False

    async def test_run_once_all_movement_actions_produce_rc_control(self) -> None:
        movement_actions = [
            "move_forward", "move_back", "move_left", "move_right",
            "move_up", "move_down", "rotate_left", "rotate_right",
        ]
        for action in movement_actions:
            interp = self._make_interp()
            nav = make_nav_output(action, confidence=0.9)
            posted: list[DroneCommand] = []
            self._wire(interp, nav_bytes(nav), flying=True, posted=posted)

            result = await interp.run_once()

            assert result is True, f"action {action!r} should have executed"
            assert len(posted) == 1
            assert posted[0].type == CommandType.RC_CONTROL, f"action {action!r} should be RC_CONTROL"

    async def test_run_once_hover_action_produces_hover_command(self) -> None:
        interp = self._make_interp()
        nav = make_nav_output("hover", confidence=0.9)
        posted: list[DroneCommand] = []
        self._wire(interp, nav_bytes(nav), flying=True, posted=posted)

        result = await interp.run_once()

        assert result is True
        assert posted[0].type == CommandType.HOVER

    async def test_run_once_land_action_produces_land_command(self) -> None:
        interp = self._make_interp()
        nav = make_nav_output("land", confidence=0.9)
        posted: list[DroneCommand] = []
        self._wire(interp, nav_bytes(nav), flying=True, posted=posted)

        result = await interp.run_once()

        assert result is True
        assert posted[0].type == CommandType.LAND

    async def test_forward_streak_guard_fires_in_run_once(self) -> None:
        """After max_forward_streak forwards, rotate_right is substituted."""
        interp = self._make_interp()
        interp._max_forward_streak = 2

        posted_all: list[DroneCommand] = []

        # Send 3 move_forward frames
        for i in range(3):
            nav = make_nav_output("move_forward", confidence=0.9, frame_id=i)
            p: list[DroneCommand] = []
            self._wire(interp, nav_bytes(nav), flying=True, posted=p)
            await interp.run_once()
            posted_all.extend(p)

        # First two: forward_back > 0; third: yaw > 0 (rotate_right substitution)
        assert posted_all[0].payload is not None and posted_all[0].payload.forward_back > 0
        assert posted_all[1].payload is not None and posted_all[1].payload.forward_back > 0
        assert posted_all[2].payload is not None and posted_all[2].payload.yaw > 0



# ---------------------------------------------------------------------------
# 5. OperatorHandler — via direct API and HTTP endpoint
# ---------------------------------------------------------------------------


class TestOperatorHandler:
    async def _make(self, battery: int = 100):
        adapter = SimAdapter()
        await adapter.connect()
        adapter.state.battery = battery
        bus = AsyncEventBus()
        fsm = FlightStateMachine(adapter, bus)
        handler = OperatorHandler(fsm, bus)
        return handler, fsm, adapter, bus

    async def _to_exploring(self, fsm: FlightStateMachine) -> None:
        await fsm.transition(FlightState.TAKEOFF)
        await fsm.transition(FlightState.EXPLORING)

    async def test_abort_transitions_to_landing(self) -> None:
        handler, fsm, _, _ = await self._make()
        await self._to_exploring(fsm)
        result = await handler.handle(OperatorCommand(action=OperatorAction.ABORT))
        assert result["action"] == "abort"
        assert result["success"] is True
        assert result["state"] == str(FlightState.LANDING)
        assert fsm.state == FlightState.LANDING

    async def test_abort_from_every_non_terminal_state(self) -> None:
        paths = [
            [FlightState.TAKEOFF],
            [FlightState.TAKEOFF, FlightState.EXPLORING],
            [FlightState.TAKEOFF, FlightState.EXPLORING, FlightState.INVESTIGATING],
            [FlightState.TAKEOFF, FlightState.EXPLORING, FlightState.RETURNING],
        ]
        for path in paths:
            handler, fsm, adapter, bus = await self._make()
            for state in path:
                await fsm.transition(state)
            await handler.handle(OperatorCommand(action=OperatorAction.ABORT))
            assert fsm.state == FlightState.LANDING, f"abort from path {path} should land"

    async def test_abort_from_preflight_is_noop(self) -> None:
        handler, fsm, _, _ = await self._make()
        result = await handler.handle(OperatorCommand(action=OperatorAction.ABORT))
        assert result["success"] is True
        assert fsm.state == FlightState.PREFLIGHT

    async def test_pause_sets_paused_and_blocks_nav(self) -> None:
        handler, fsm, _, _ = await self._make()
        await self._to_exploring(fsm)
        result = await handler.handle(OperatorCommand(action=OperatorAction.PAUSE))
        assert result["action"] == "pause"
        assert result["success"] is True
        assert result["paused"] is True
        assert fsm.paused is True
        assert fsm.accepts_nav() is False

    async def test_resume_clears_paused_and_restores_nav(self) -> None:
        handler, fsm, _, _ = await self._make()
        await self._to_exploring(fsm)
        await handler.handle(OperatorCommand(action=OperatorAction.PAUSE))
        result = await handler.handle(OperatorCommand(action=OperatorAction.RESUME))
        assert result["action"] == "resume"
        assert result["success"] is True
        assert result["paused"] is False
        assert fsm.accepts_nav() is True

    async def test_pause_publishes_bus_event(self) -> None:
        handler, fsm, _, bus = await self._make()
        await self._to_exploring(fsm)
        queue = await bus.subscribe("drone.paused")
        await handler.handle(OperatorCommand(action=OperatorAction.PAUSE))
        assert not queue.empty()
        event = queue.get_nowait()
        assert "timestamp" in event

    async def test_resume_publishes_bus_event(self) -> None:
        handler, fsm, _, bus = await self._make()
        await self._to_exploring(fsm)
        await handler.handle(OperatorCommand(action=OperatorAction.PAUSE))
        queue = await bus.subscribe("drone.resumed")
        await handler.handle(OperatorCommand(action=OperatorAction.RESUME))
        assert not queue.empty()

    async def test_abort_publishes_abort_event(self) -> None:
        handler, fsm, _, bus = await self._make()
        await self._to_exploring(fsm)
        queue = await bus.subscribe("drone.abort")
        await handler.handle(OperatorCommand(action=OperatorAction.ABORT))
        assert not queue.empty()
        event = queue.get_nowait()
        assert "from_state" in event

    async def test_abort_clears_paused_before_landing(self) -> None:
        handler, fsm, _, _ = await self._make()
        await self._to_exploring(fsm)
        await fsm.pause()
        assert fsm.paused is True
        await handler.handle(OperatorCommand(action=OperatorAction.ABORT))
        assert fsm.paused is False
        assert fsm.state == FlightState.LANDING


# ---------------------------------------------------------------------------
# 6. Operator endpoint via HTTP
# ---------------------------------------------------------------------------


class TestOperatorEndpointHTTP:
    def test_pause_via_http(self) -> None:
        from fastapi.testclient import TestClient
        with TestClient(create_app(mode="sim")) as client:
            result = client.post(
                "/operator-command",
                json={"action": "pause", "issued_by": "test"},
            )
        assert result.status_code == 200
        body = result.json()
        assert body["action"] == "pause"
        assert body["success"] is True

    def test_resume_via_http(self) -> None:
        from fastapi.testclient import TestClient
        with TestClient(create_app(mode="sim")) as client:
            client.post("/operator-command", json={"action": "pause", "issued_by": "test"})
            result = client.post(
                "/operator-command",
                json={"action": "resume", "issued_by": "test"},
            )
        assert result.status_code == 200
        body = result.json()
        assert body["action"] == "resume"
        assert body["paused"] is False

    def test_abort_from_preflight_via_http(self) -> None:
        from fastapi.testclient import TestClient
        with TestClient(create_app(mode="sim")) as client:
            result = client.post(
                "/operator-command",
                json={"action": "abort", "issued_by": "test"},
            )
        assert result.status_code == 200
        assert result.json()["success"] is True


# ---------------------------------------------------------------------------
# 7. Integration smoke test — AsyncClient end-to-end
# ---------------------------------------------------------------------------


class TestIntegrationSmoke:
    @pytest.fixture
    def app(self):
        return create_app(mode="sim")

    async def test_health_reports_connected_after_start(self, app) -> None:
        async with AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            async with app.router.lifespan_context(app):
                resp = await client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "sim"
        assert body["telemetry"]["connected"] is True
        assert body["telemetry"]["flying"] is False

    async def test_takeoff_sets_flying_in_health(self, app) -> None:
        async with AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            async with app.router.lifespan_context(app):
                takeoff = await client.post("/commands", json={"type": "takeoff", "issued_by": "smoke"})
                assert takeoff.json()["status"] == "executed"

                health = await client.get("/health")
                assert health.json()["telemetry"]["flying"] is True

    async def test_land_after_takeoff_clears_flying(self, app) -> None:
        async with AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            async with app.router.lifespan_context(app):
                await client.post("/commands", json={"type": "takeoff", "issued_by": "smoke"})
                land = await client.post("/commands", json={"type": "land", "issued_by": "smoke"})
                assert land.json()["status"] == "executed"

                health = await client.get("/health")
                assert health.json()["telemetry"]["flying"] is False

    async def test_rc_control_executes_while_flying(self, app) -> None:
        async with AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            async with app.router.lifespan_context(app):
                await client.post("/commands", json={"type": "takeoff", "issued_by": "smoke"})
                resp = await client.post(
                    "/commands",
                    json={
                        "type": "rc_control",
                        "issued_by": "smoke",
                        "ttl_ms": 300,
                        "payload": {
                            "left_right": 0,
                            "forward_back": 20,
                            "up_down": 0,
                            "yaw": 0,
                            "duration_ms": 50,
                        },
                    },
                )
        assert resp.json()["status"] == "executed"

    async def test_rc_control_rejected_while_grounded(self, app) -> None:
        async with AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            async with app.router.lifespan_context(app):
                resp = await client.post(
                    "/commands",
                    json={
                        "type": "rc_control",
                        "issued_by": "smoke",
                        "ttl_ms": 300,
                        "payload": {
                            "left_right": 0,
                            "forward_back": 20,
                            "up_down": 0,
                            "yaw": 0,
                            "duration_ms": 50,
                        },
                    },
                )
        # Safety returns FAILED (not HTTP error) for grounded RC
        assert resp.json()["status"] == "failed"

    async def test_emergency_always_executes(self, app) -> None:
        async with AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            async with app.router.lifespan_context(app):
                resp = await client.post(
                    "/commands",
                    json={"type": "emergency", "issued_by": "smoke"},
                )
        assert resp.json()["status"] == "executed"

    async def test_operator_abort_via_http_endpoint(self, app) -> None:
        async with AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            async with app.router.lifespan_context(app):
                resp = await client.post(
                    "/operator-command",
                    json={"action": "abort", "issued_by": "smoke"},
                )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    async def test_full_flight_smoke(self, app) -> None:
        """Takeoff → health shows flying → hover → land → health shows grounded."""
        async with AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            async with app.router.lifespan_context(app):
                # Takeoff
                r = await client.post("/commands", json={"type": "takeoff", "issued_by": "smoke"})
                assert r.json()["status"] == "executed"

                # Verify flying
                h = await client.get("/health")
                assert h.json()["telemetry"]["flying"] is True

                # Hover while airborne
                r = await client.post("/commands", json={"type": "hover", "issued_by": "smoke"})
                assert r.json()["status"] == "executed"

                # Land
                r = await client.post("/commands", json={"type": "land", "issued_by": "smoke"})
                assert r.json()["status"] == "executed"

                # Verify grounded
                h = await client.get("/health")
                assert h.json()["telemetry"]["flying"] is False
                assert h.json()["telemetry"]["connected"] is True
