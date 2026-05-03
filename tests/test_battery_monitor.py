from __future__ import annotations

import asyncio

import pytest

from breacheye.adapters.sim import SimAdapter
from breacheye.battery_monitor import BatteryMonitor
from breacheye.bus import AsyncEventBus
from breacheye.state_machine import FlightState, FlightStateMachine


def make_monitor(
    battery: int = 100,
    poll_interval: float = 0.05,
    rtl_threshold: int = 15,
    land_threshold: int = 10,
) -> tuple[BatteryMonitor, FlightStateMachine, SimAdapter, AsyncEventBus]:
    adapter = SimAdapter()
    adapter.state.battery = battery
    adapter.state.connected = True
    bus = AsyncEventBus()
    fsm = FlightStateMachine(adapter, bus)
    monitor = BatteryMonitor(
        fsm,
        adapter,
        bus,
        poll_interval=poll_interval,
        rtl_threshold=rtl_threshold,
        land_threshold=land_threshold,
    )
    return monitor, fsm, adapter, bus


async def _advance_to_exploring(fsm: FlightStateMachine, adapter: SimAdapter) -> None:
    """Drive FSM from PREFLIGHT to EXPLORING via connect + transitions."""
    await adapter.connect()
    await fsm.transition(FlightState.TAKEOFF)
    await fsm.transition(FlightState.EXPLORING)


async def test_telemetry_updates_on_poll() -> None:
    monitor, fsm, adapter, bus = make_monitor(battery=75)
    try:
        await monitor.start()
        await asyncio.sleep(0.15)
        telem = monitor.telemetry
        assert telem["battery"] == 75
    finally:
        await monitor.stop()


async def test_rtl_at_low_battery() -> None:
    monitor, fsm, adapter, bus = make_monitor(battery=100)
    try:
        await _advance_to_exploring(fsm, adapter)
        adapter.state.battery = 14
        await monitor.start()
        await asyncio.sleep(0.15)
        assert fsm.state == FlightState.RETURNING
    finally:
        await monitor.stop()


async def test_landing_at_critical_battery() -> None:
    monitor, fsm, adapter, bus = make_monitor(battery=100)
    try:
        await _advance_to_exploring(fsm, adapter)
        adapter.state.battery = 9
        await monitor.start()
        await asyncio.sleep(0.15)
        assert fsm.state == FlightState.LANDING
    finally:
        await monitor.stop()


async def test_no_action_above_threshold() -> None:
    monitor, fsm, adapter, bus = make_monitor(battery=50)
    try:
        await _advance_to_exploring(fsm, adapter)
        await monitor.start()
        await asyncio.sleep(0.15)
        assert fsm.state == FlightState.EXPLORING
    finally:
        await monitor.stop()


async def test_battery_warning_event_published() -> None:
    monitor, fsm, adapter, bus = make_monitor(battery=100)
    q = await bus.subscribe("drone.battery_warning")
    try:
        await _advance_to_exploring(fsm, adapter)
        adapter.state.battery = 14
        await monitor.start()
        await asyncio.sleep(0.15)
        assert not q.empty()
        event = q.get_nowait()
        assert event["level"] == "low"
        assert event["battery"] == 14
    finally:
        await monitor.stop()


async def test_monitor_ignores_non_active_states() -> None:
    monitor, fsm, adapter, bus = make_monitor(battery=5)
    # FSM stays in PREFLIGHT — adapter connected but no takeoff
    adapter.state.connected = True
    try:
        await monitor.start()
        await asyncio.sleep(0.15)
        assert fsm.state == FlightState.PREFLIGHT
    finally:
        await monitor.stop()


async def test_stop_cancels_task() -> None:
    monitor, fsm, adapter, bus = make_monitor(battery=100)
    await monitor.start()
    # Should complete without raising
    await monitor.stop()
    # Second stop is a no-op — task already cancelled
    await monitor.stop()
