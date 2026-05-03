from __future__ import annotations

import asyncio

import pytest

from breacheye.adapters.sim import SimAdapter
from breacheye.bus import AsyncEventBus
from breacheye.state_machine import (
    FlightState,
    FlightStateMachine,
    InvalidTransition,
    PreflightFailed,
)


def make_fsm(
    battery: int = 100, connected: bool = True
) -> tuple[FlightStateMachine, SimAdapter, AsyncEventBus]:
    adapter = SimAdapter()
    adapter.state.battery = battery
    adapter.state.connected = connected
    bus = AsyncEventBus()
    fsm = FlightStateMachine(adapter, bus)
    return fsm, adapter, bus


async def _connect(adapter: SimAdapter) -> None:
    """Connect without appending duplicate connect command if already connected."""
    if not adapter.state.connected:
        await adapter.connect()


# ---------------------------------------------------------------------------
# State tests
# ---------------------------------------------------------------------------


async def test_initial_state_is_preflight() -> None:
    fsm, _, _ = make_fsm()
    assert fsm.state == FlightState.PREFLIGHT


async def test_full_lifecycle() -> None:
    fsm, adapter, _ = make_fsm()
    await adapter.connect()

    await fsm.transition(FlightState.TAKEOFF)
    assert fsm.state == FlightState.TAKEOFF

    await fsm.transition(FlightState.EXPLORING)
    assert fsm.state == FlightState.EXPLORING

    await fsm.transition(FlightState.INVESTIGATING)
    assert fsm.state == FlightState.INVESTIGATING

    await fsm.transition(FlightState.EXPLORING)
    assert fsm.state == FlightState.EXPLORING

    await fsm.transition(FlightState.RETURNING)
    assert fsm.state == FlightState.RETURNING

    await fsm.transition(FlightState.LANDING)
    assert fsm.state == FlightState.LANDING

    await fsm.transition(FlightState.COMPLETE)
    assert fsm.state == FlightState.COMPLETE


async def test_invalid_transition_raises() -> None:
    fsm, adapter, _ = make_fsm()
    await adapter.connect()

    with pytest.raises(InvalidTransition) as exc_info:
        await fsm.transition(FlightState.EXPLORING)

    assert exc_info.value.from_state == FlightState.PREFLIGHT
    assert exc_info.value.to_state == FlightState.EXPLORING


async def test_landing_to_exploring_raises() -> None:
    fsm, adapter, _ = make_fsm()
    await adapter.connect()

    await fsm.transition(FlightState.TAKEOFF)
    await fsm.transition(FlightState.EXPLORING)
    await fsm.transition(FlightState.RETURNING)
    await fsm.transition(FlightState.LANDING)

    with pytest.raises(InvalidTransition):
        await fsm.transition(FlightState.EXPLORING)


async def test_complete_is_terminal() -> None:
    fsm, adapter, _ = make_fsm()
    await adapter.connect()

    await fsm.transition(FlightState.TAKEOFF)
    await fsm.transition(FlightState.EXPLORING)
    await fsm.transition(FlightState.RETURNING)
    await fsm.transition(FlightState.LANDING)
    await fsm.transition(FlightState.COMPLETE)

    for target in FlightState:
        with pytest.raises(InvalidTransition):
            await fsm.transition(target)


# ---------------------------------------------------------------------------
# Preflight check tests
# ---------------------------------------------------------------------------


async def test_preflight_check_passes() -> None:
    fsm, adapter, _ = make_fsm(battery=100, connected=True)
    await adapter.connect()
    checks = await fsm.preflight_check()
    assert checks["passed"] is True
    assert checks["connected"] is True
    assert checks["battery_ok"] is True
    assert checks["battery"] == 100


async def test_preflight_check_fails_low_battery() -> None:
    fsm, adapter, _ = make_fsm(battery=10, connected=True)
    await adapter.connect()
    checks = await fsm.preflight_check()
    assert checks["passed"] is False
    assert checks["battery_ok"] is False


async def test_preflight_check_fails_disconnected() -> None:
    fsm, adapter, _ = make_fsm(battery=100, connected=False)
    # Do NOT call connect — adapter.state.connected is False
    checks = await fsm.preflight_check()
    assert checks["passed"] is False
    assert checks["connected"] is False


# ---------------------------------------------------------------------------
# Guard tests
# ---------------------------------------------------------------------------


async def test_takeoff_guard_rejects_low_battery() -> None:
    fsm, adapter, _ = make_fsm(battery=10, connected=True)
    await adapter.connect()

    with pytest.raises(PreflightFailed) as exc_info:
        await fsm.transition(FlightState.TAKEOFF)

    assert exc_info.value.checks["battery_ok"] is False


# ---------------------------------------------------------------------------
# Bus event tests
# ---------------------------------------------------------------------------


async def test_state_change_events_published() -> None:
    fsm, adapter, bus = make_fsm()
    await adapter.connect()

    queue = await bus.subscribe("drone.state_change")

    await fsm.transition(FlightState.TAKEOFF)
    await fsm.transition(FlightState.EXPLORING)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    assert len(events) == 2

    assert events[0]["from_state"] == str(FlightState.PREFLIGHT)
    assert events[0]["to_state"] == str(FlightState.TAKEOFF)
    assert "timestamp" in events[0]

    assert events[1]["from_state"] == str(FlightState.TAKEOFF)
    assert events[1]["to_state"] == str(FlightState.EXPLORING)


# ---------------------------------------------------------------------------
# accepts_nav tests
# ---------------------------------------------------------------------------


async def test_accepts_nav_in_exploring() -> None:
    fsm, adapter, _ = make_fsm()
    await adapter.connect()
    await fsm.transition(FlightState.TAKEOFF)
    await fsm.transition(FlightState.EXPLORING)
    assert fsm.accepts_nav() is True


async def test_accepts_nav_in_investigating() -> None:
    fsm, adapter, _ = make_fsm()
    await adapter.connect()
    await fsm.transition(FlightState.TAKEOFF)
    await fsm.transition(FlightState.EXPLORING)
    await fsm.transition(FlightState.INVESTIGATING)
    assert fsm.accepts_nav() is True


async def test_rejects_nav_in_preflight() -> None:
    fsm, _, _ = make_fsm()
    assert fsm.accepts_nav() is False


async def test_rejects_nav_in_landing() -> None:
    fsm, adapter, _ = make_fsm()
    await adapter.connect()
    await fsm.transition(FlightState.TAKEOFF)
    await fsm.transition(FlightState.EXPLORING)
    await fsm.transition(FlightState.RETURNING)
    await fsm.transition(FlightState.LANDING)
    assert fsm.accepts_nav() is False


# ---------------------------------------------------------------------------
# Adapter command verification
# ---------------------------------------------------------------------------


async def test_adapter_commands_issued() -> None:
    fsm, adapter, _ = make_fsm()
    await adapter.connect()

    await fsm.transition(FlightState.TAKEOFF)
    await fsm.transition(FlightState.EXPLORING)

    assert ("takeoff", ()) in adapter.commands
    assert ("hover", (0, 0, 0, 0)) in adapter.commands


async def test_preflight_to_landing_allowed() -> None:
    """Abort from PREFLIGHT skips flying guard (drone never took off)."""
    fsm, adapter, _ = make_fsm()
    await adapter.connect()
    await fsm.transition(FlightState.LANDING)
    assert fsm.state == FlightState.LANDING


async def test_takeoff_to_landing_allowed() -> None:
    """Battery emergency during climb must reach LANDING."""
    fsm, adapter, _ = make_fsm()
    await adapter.connect()
    await fsm.transition(FlightState.TAKEOFF)
    await fsm.transition(FlightState.LANDING)
    assert fsm.state == FlightState.LANDING
