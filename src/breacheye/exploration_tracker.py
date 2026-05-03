from __future__ import annotations

import asyncio
import logging
from time import time

from breacheye.bus import AsyncEventBus
from breacheye.state_machine import FlightState, FlightStateMachine, InvalidTransition


class ExplorationTracker:
    """Tracks exploration progress from NavigationOutput decisions."""

    def __init__(self, fsm: FlightStateMachine, bus: AsyncEventBus) -> None:
        self._fsm = fsm
        self._bus = bus
        self._areas_visited: set[str] = set()
        self._pois_found: int = 0
        self._last_exploration_state: str = "exploring"
        self._task: asyncio.Task | None = None
        self._queue: asyncio.Queue | None = None

    @property
    def coverage_stats(self) -> dict:
        """Expose stats for UI."""
        return {
            "areas_visited": len(self._areas_visited),
            "pois_found": self._pois_found,
            "last_exploration_state": self._last_exploration_state,
        }

    def record_poi(self) -> None:
        """Increment POI counter (called externally when detection confirms a POI)."""
        self._pois_found += 1

    async def start(self) -> None:
        """Subscribe to nav decisions on the bus and process them."""
        self._queue = await self._bus.subscribe("drone.nav_decision")
        self._task = asyncio.create_task(self._process_loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._queue is not None:
            await self._bus.unsubscribe("drone.nav_decision", self._queue)

    async def _process_loop(self) -> None:
        assert self._queue is not None
        while True:
            try:
                nav_output = await self._queue.get()
                await self._handle_nav(nav_output)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logging.getLogger(__name__).warning("exploration tracker error: %s", exc)

    async def _handle_nav(self, nav_output: dict) -> None:
        """Process a NavigationOutput dict from the bus."""
        decision = nav_output.get("decision", {})
        exploration_state = decision.get("exploration_state", "exploring")
        self._last_exploration_state = exploration_state

        reasoning = decision.get("reasoning", "")
        if reasoning:
            area_key = f"area-{hash(reasoning) % 10000}"
            self._areas_visited.add(area_key)

        if exploration_state == "coverage_complete":
            if self._fsm.state in (FlightState.EXPLORING, FlightState.INVESTIGATING):
                try:
                    await self._fsm.transition(FlightState.RETURNING)
                    await self._bus.publish("drone.exploration_event", {
                        "event": "coverage_complete",
                        "stats": self.coverage_stats,
                        "timestamp": time(),
                    })
                except InvalidTransition:
                    pass

        elif exploration_state == "low_battery":
            if self._fsm.state in (FlightState.EXPLORING, FlightState.INVESTIGATING):
                try:
                    await self._fsm.transition(FlightState.RETURNING)
                    await self._bus.publish("drone.exploration_event", {
                        "event": "low_battery_nav",
                        "stats": self.coverage_stats,
                        "timestamp": time(),
                    })
                except InvalidTransition:
                    pass

        elif exploration_state == "investigating_poi":
            if self._fsm.state == FlightState.EXPLORING:
                try:
                    await self._fsm.transition(FlightState.INVESTIGATING)
                except InvalidTransition:
                    pass

        elif exploration_state == "exploring":
            if self._fsm.state == FlightState.INVESTIGATING:
                try:
                    await self._fsm.transition(FlightState.EXPLORING)
                except InvalidTransition:
                    pass
