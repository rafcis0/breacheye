from __future__ import annotations

import pytest

from breacheye.adapters.sim import SimAdapter
from breacheye.bus import AsyncEventBus
from breacheye.operator import OperatorAction, OperatorCommand, OperatorHandler
from breacheye.state_machine import FlightState, FlightStateMachine


async def make_handler(battery: int = 100):
    adapter = SimAdapter()
    adapter.state.connected = True
    adapter.state.battery = battery
    bus = AsyncEventBus()
    fsm = FlightStateMachine(adapter, bus)
    await adapter.connect()
    handler = OperatorHandler(fsm, bus)
    return handler, fsm, adapter, bus


async def _to_exploring(fsm: FlightStateMachine) -> None:
    await fsm.transition(FlightState.TAKEOFF)
    await fsm.transition(FlightState.EXPLORING)


async def _to_investigating(fsm: FlightStateMachine) -> None:
    await fsm.transition(FlightState.TAKEOFF)
    await fsm.transition(FlightState.EXPLORING)
    await fsm.transition(FlightState.INVESTIGATING)


async def _to_complete(fsm: FlightStateMachine) -> None:
    await fsm.transition(FlightState.TAKEOFF)
    await fsm.transition(FlightState.EXPLORING)
    await fsm.transition(FlightState.RETURNING)
    await fsm.transition(FlightState.LANDING)
    await fsm.transition(FlightState.COMPLETE)


# ---------------------------------------------------------------------------
# pause / resume tests
# ---------------------------------------------------------------------------


async def test_pause_during_exploring() -> None:
    _, fsm, _, _ = await make_handler()
    await _to_exploring(fsm)
    await fsm.pause()
    assert fsm.paused is True
    assert fsm.accepts_nav() is False


async def test_resume_after_pause() -> None:
    _, fsm, _, _ = await make_handler()
    await _to_exploring(fsm)
    await fsm.pause()
    await fsm.resume()
    assert fsm.paused is False
    assert fsm.accepts_nav() is True


# ---------------------------------------------------------------------------
# abort tests
# ---------------------------------------------------------------------------


async def test_abort_from_exploring() -> None:
    _, fsm, _, _ = await make_handler()
    await _to_exploring(fsm)
    await fsm.abort()
    assert fsm.state == FlightState.LANDING


async def test_abort_from_investigating() -> None:
    _, fsm, _, _ = await make_handler()
    await _to_investigating(fsm)
    await fsm.abort()
    assert fsm.state == FlightState.LANDING


async def test_abort_from_takeoff() -> None:
    _, fsm, _, _ = await make_handler()
    await fsm.transition(FlightState.TAKEOFF)
    await fsm.abort()
    assert fsm.state == FlightState.LANDING


async def test_abort_from_complete_is_noop() -> None:
    _, fsm, _, _ = await make_handler()
    await _to_complete(fsm)
    await fsm.abort()
    assert fsm.state == FlightState.COMPLETE


async def test_abort_from_preflight_is_noop() -> None:
    _, fsm, _, _ = await make_handler()
    assert fsm.state == FlightState.PREFLIGHT
    await fsm.abort()
    assert fsm.state == FlightState.PREFLIGHT


async def test_abort_clears_paused_flag() -> None:
    _, fsm, _, _ = await make_handler()
    await _to_exploring(fsm)
    await fsm.pause()
    assert fsm.paused is True
    await fsm.abort()
    assert fsm.paused is False


# ---------------------------------------------------------------------------
# event publication tests
# ---------------------------------------------------------------------------


async def test_pause_publishes_event() -> None:
    _, fsm, _, bus = await make_handler()
    await _to_exploring(fsm)
    queue = await bus.subscribe("drone.paused")
    await fsm.pause()
    assert not queue.empty()
    event = queue.get_nowait()
    assert "timestamp" in event


async def test_resume_publishes_event() -> None:
    _, fsm, _, bus = await make_handler()
    await _to_exploring(fsm)
    await fsm.pause()
    queue = await bus.subscribe("drone.resumed")
    await fsm.resume()
    assert not queue.empty()
    event = queue.get_nowait()
    assert "timestamp" in event


async def test_abort_publishes_event() -> None:
    _, fsm, _, bus = await make_handler()
    await _to_exploring(fsm)
    queue = await bus.subscribe("drone.abort")
    await fsm.abort()
    assert not queue.empty()
    event = queue.get_nowait()
    assert "from_state" in event
    assert "timestamp" in event


# ---------------------------------------------------------------------------
# OperatorHandler tests
# ---------------------------------------------------------------------------


async def test_handler_abort() -> None:
    handler, fsm, _, _ = await make_handler()
    await _to_exploring(fsm)
    result = await handler.handle(OperatorCommand(action=OperatorAction.ABORT))
    assert result["action"] == "abort"
    assert result["success"] is True
    assert result["state"] == str(FlightState.LANDING)


async def test_handler_pause_resume() -> None:
    handler, fsm, _, _ = await make_handler()
    await _to_exploring(fsm)

    pause_result = await handler.handle(OperatorCommand(action=OperatorAction.PAUSE))
    assert pause_result["action"] == "pause"
    assert pause_result["success"] is True
    assert pause_result["paused"] is True

    resume_result = await handler.handle(OperatorCommand(action=OperatorAction.RESUME))
    assert resume_result["action"] == "resume"
    assert resume_result["success"] is True
    assert resume_result["paused"] is False


# ---------------------------------------------------------------------------
# idempotency tests
# ---------------------------------------------------------------------------


async def test_double_pause_is_idempotent() -> None:
    _, fsm, _, _ = await make_handler()
    await _to_exploring(fsm)
    await fsm.pause()
    await fsm.pause()
    assert fsm.paused is True


async def test_double_resume_is_idempotent() -> None:
    _, fsm, _, _ = await make_handler()
    await _to_exploring(fsm)
    # resume without pausing first — should not error
    await fsm.resume()
    assert fsm.paused is False
