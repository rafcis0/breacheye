from __future__ import annotations

from enum import StrEnum
from time import time
from typing import TYPE_CHECKING

from breacheye.adapters.base import DroneAdapter
from breacheye.bus import AsyncEventBus

if TYPE_CHECKING:
    pass


class FlightState(StrEnum):
    PREFLIGHT = "preflight"
    TAKEOFF = "takeoff"
    EXPLORING = "exploring"
    INVESTIGATING = "investigating"
    RETURNING = "returning"
    LANDING = "landing"
    COMPLETE = "complete"


# LANDING reachable from every non-terminal state (battery emergency, operator ABORT).
# ExplorationState mapping: coverage_complete → RETURNING, low_battery → battery monitor
# triggers LANDING, obstacle_avoidance → transient within EXPLORING.
TRANSITIONS: dict[FlightState, set[FlightState]] = {
    FlightState.PREFLIGHT: {FlightState.TAKEOFF, FlightState.LANDING},
    FlightState.TAKEOFF: {FlightState.EXPLORING, FlightState.LANDING},
    FlightState.EXPLORING: {
        FlightState.INVESTIGATING,
        FlightState.RETURNING,
        FlightState.LANDING,
    },
    FlightState.INVESTIGATING: {
        FlightState.EXPLORING,
        FlightState.RETURNING,
        FlightState.LANDING,
    },
    FlightState.RETURNING: {FlightState.LANDING},
    FlightState.LANDING: {FlightState.COMPLETE},
    FlightState.COMPLETE: set(),
}


class InvalidTransition(Exception):
    def __init__(self, from_state: FlightState, to_state: FlightState) -> None:
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"cannot transition from {from_state} to {to_state}")


class PreflightFailed(Exception):
    def __init__(self, checks: dict) -> None:
        self.checks = checks
        super().__init__(f"preflight failed: {checks}")


class FlightStateMachine:
    def __init__(self, adapter: DroneAdapter, bus: AsyncEventBus) -> None:
        self._adapter = adapter
        self._bus = bus
        self._state = FlightState.PREFLIGHT
        self._min_battery = 20
        self._paused = False

    @property
    def state(self) -> FlightState:
        return self._state

    @property
    def paused(self) -> bool:
        return self._paused

    def accepts_nav(self) -> bool:
        """Whether nav decisions from NavInterpreter should be executed."""
        return self._state in (FlightState.EXPLORING, FlightState.INVESTIGATING) and not self._paused

    async def pause(self) -> None:
        """Pause autonomous navigation. Drone hovers in place."""
        if self._paused:
            return
        self._paused = True
        if self._state in (FlightState.EXPLORING, FlightState.INVESTIGATING):
            await self._adapter.hover()
        await self._bus.publish("drone.paused", {"timestamp": time()})

    async def resume(self) -> None:
        """Resume autonomous navigation."""
        if not self._paused:
            return
        self._paused = False
        await self._bus.publish("drone.resumed", {"timestamp": time()})

    async def abort(self) -> None:
        """Emergency abort — transition to LANDING from any non-terminal state."""
        if self._state in (FlightState.COMPLETE, FlightState.PREFLIGHT):
            return
        self._paused = False
        await self._bus.publish("drone.abort", {"from_state": str(self._state), "timestamp": time()})
        try:
            await self.transition(FlightState.LANDING)
        except InvalidTransition:
            pass

    async def transition(self, target: FlightState) -> None:
        """Attempt state transition. Raises InvalidTransition on illegal moves."""
        if target not in TRANSITIONS[self._state]:
            raise InvalidTransition(self._state, target)

        await self._run_guard(target)
        await self._run_entry_action(target)

        from_state = self._state
        self._state = target

        await self._bus.publish(
            "drone.state_change",
            {
                "from_state": str(from_state),
                "to_state": str(target),
                "timestamp": time(),
            },
        )

    async def mark_airborne_for_nav(self) -> None:
        """Record an externally executed takeoff and enable autonomous nav."""
        if self._state == FlightState.PREFLIGHT:
            await self._set_state_without_entry(FlightState.TAKEOFF)
        if self._state == FlightState.TAKEOFF:
            await self._set_state_without_entry(FlightState.EXPLORING)

    async def mark_grounded(self) -> None:
        """Record an externally executed land/emergency and disable nav."""
        self._paused = False
        if self._state in (FlightState.COMPLETE, FlightState.PREFLIGHT):
            return
        if self._state != FlightState.LANDING:
            await self._set_state_without_entry(FlightState.LANDING)
        await self._set_state_without_entry(FlightState.COMPLETE)

    async def _set_state_without_entry(self, target: FlightState) -> None:
        if target == self._state:
            return
        from_state = self._state
        self._state = target
        await self._bus.publish(
            "drone.state_change",
            {
                "from_state": str(from_state),
                "to_state": str(target),
                "timestamp": time(),
            },
        )

    async def _run_guard(self, target: FlightState) -> None:
        if target == FlightState.TAKEOFF:
            checks = await self.preflight_check()
            if not checks["passed"]:
                raise PreflightFailed(checks)
        elif target == FlightState.LANDING and self._state != FlightState.PREFLIGHT:
            drone_state = await self._adapter.get_state()
            if not drone_state.flying:
                raise RuntimeError("cannot land: drone is not flying")

    async def _run_entry_action(self, target: FlightState) -> None:
        if target == FlightState.TAKEOFF:
            await self._adapter.takeoff()
        elif target == FlightState.LANDING:
            await self._adapter.land()
        elif target in (
            FlightState.EXPLORING,
            FlightState.INVESTIGATING,
            FlightState.RETURNING,
        ):
            await self._adapter.hover()

    async def preflight_check(self) -> dict:
        """Run preflight checks. Returns dict with check results."""
        state = await self._adapter.get_state()
        battery_ok = (state.battery or 0) > self._min_battery
        return {
            "connected": state.connected,
            "battery_ok": battery_ok,
            "battery": state.battery,
            "passed": state.connected and battery_ok,
        }

    async def run_lifecycle(self) -> None:
        """Run full PREFLIGHT -> EXPLORING lifecycle. Convenience for sim/test."""
        await self.transition(FlightState.TAKEOFF)
        await self.transition(FlightState.EXPLORING)
