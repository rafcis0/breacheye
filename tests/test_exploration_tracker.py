from __future__ import annotations

import asyncio

import pytest

from breacheye.adapters.sim import SimAdapter
from breacheye.bus import AsyncEventBus
from breacheye.exploration_tracker import ExplorationTracker
from breacheye.state_machine import FlightState, FlightStateMachine


async def make_tracker() -> tuple[ExplorationTracker, FlightStateMachine, SimAdapter, AsyncEventBus]:
    adapter = SimAdapter()
    adapter.state.connected = True
    adapter.state.battery = 100
    bus = AsyncEventBus()
    fsm = FlightStateMachine(adapter, bus)
    await adapter.connect()
    await fsm.transition(FlightState.TAKEOFF)
    await fsm.transition(FlightState.EXPLORING)
    tracker = ExplorationTracker(fsm, bus)
    return tracker, fsm, adapter, bus


def _nav_payload(exploration_state: str, reasoning: str = "clear corridor ahead") -> dict:
    return {
        "frame_id": 1,
        "timestamp": 1746201234.0,
        "decision": {
            "action": "move_forward",
            "params": {"distance_cm": 50},
            "confidence": 0.85,
            "reasoning": reasoning,
            "exploration_state": exploration_state,
        },
    }


async def test_coverage_complete_triggers_returning() -> None:
    tracker, fsm, _, bus = await make_tracker()
    await tracker.start()
    try:
        await bus.publish("drone.nav_decision", _nav_payload("coverage_complete"))
        await asyncio.sleep(0.05)
        assert fsm.state == FlightState.RETURNING
    finally:
        await tracker.stop()


async def test_low_battery_nav_triggers_returning() -> None:
    tracker, fsm, _, bus = await make_tracker()
    await tracker.start()
    try:
        await bus.publish("drone.nav_decision", _nav_payload("low_battery"))
        await asyncio.sleep(0.05)
        assert fsm.state == FlightState.RETURNING
    finally:
        await tracker.stop()


async def test_investigating_poi_triggers_investigating() -> None:
    tracker, fsm, _, bus = await make_tracker()
    await tracker.start()
    try:
        await bus.publish("drone.nav_decision", _nav_payload("investigating_poi"))
        await asyncio.sleep(0.05)
        assert fsm.state == FlightState.INVESTIGATING
    finally:
        await tracker.stop()


async def test_exploring_from_investigating() -> None:
    tracker, fsm, _, bus = await make_tracker()
    # Manually move FSM to INVESTIGATING first
    await fsm.transition(FlightState.INVESTIGATING)
    await tracker.start()
    try:
        await bus.publish("drone.nav_decision", _nav_payload("exploring"))
        await asyncio.sleep(0.05)
        assert fsm.state == FlightState.EXPLORING
    finally:
        await tracker.stop()


async def test_coverage_stats_tracked() -> None:
    tracker, fsm, _, bus = await make_tracker()
    await tracker.start()
    try:
        await bus.publish("drone.nav_decision", _nav_payload("exploring", reasoning="hallway A"))
        await bus.publish("drone.nav_decision", _nav_payload("exploring", reasoning="room B"))
        await bus.publish("drone.nav_decision", _nav_payload("exploring", reasoning="stairwell C"))
        await asyncio.sleep(0.05)
        assert tracker.coverage_stats["areas_visited"] > 0
    finally:
        await tracker.stop()


async def test_record_poi_increments() -> None:
    tracker, _, _, _ = await make_tracker()
    tracker.record_poi()
    tracker.record_poi()
    tracker.record_poi()
    assert tracker.coverage_stats["pois_found"] == 3


async def test_exploration_event_published() -> None:
    tracker, fsm, _, bus = await make_tracker()
    event_queue = await bus.subscribe("drone.exploration_event")
    await tracker.start()
    try:
        await bus.publish("drone.nav_decision", _nav_payload("coverage_complete"))
        await asyncio.sleep(0.05)
        assert not event_queue.empty()
        event = event_queue.get_nowait()
        assert event["event"] == "coverage_complete"
        assert "stats" in event
        assert "timestamp" in event
    finally:
        await tracker.stop()
