from __future__ import annotations

import asyncio
import logging
from time import time

from breacheye.adapters.base import DroneAdapter
from breacheye.bus import AsyncEventBus
from breacheye.state_machine import FlightState, FlightStateMachine, InvalidTransition


class BatteryMonitor:
    def __init__(
        self,
        fsm: FlightStateMachine,
        adapter: DroneAdapter,
        bus: AsyncEventBus,
        poll_interval: float = 2.0,
        rtl_threshold: int = 15,
        land_threshold: int = 10,
    ) -> None:
        self._fsm = fsm
        self._adapter = adapter
        self._bus = bus
        self._poll_interval = poll_interval
        self._rtl_threshold = rtl_threshold
        self._land_threshold = land_threshold

        self._battery: int | None = None
        self._height_cm: int | None = None
        self._flight_time_s: int | None = None
        self._task: asyncio.Task | None = None

    @property
    def telemetry(self) -> dict:
        """Latest telemetry snapshot for UI consumption."""
        return {
            "battery": self._battery,
            "height_cm": self._height_cm,
            "flight_time_s": self._flight_time_s,
        }

    async def start(self) -> None:
        """Start the polling loop as an asyncio task."""
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        """Cancel the polling task."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _poll_loop(self) -> None:
        """Poll adapter state every poll_interval seconds."""
        while True:
            try:
                state = await self._adapter.get_state()
                self._battery = state.battery
                self._height_cm = state.height_cm
                self._flight_time_s = state.flight_time_s

                await self._check_battery(state.battery)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logging.getLogger(__name__).warning("battery poll failed: %s", exc)

            await asyncio.sleep(self._poll_interval)

    async def _check_battery(self, battery: int | None) -> None:
        """Trigger state transitions based on battery level."""
        if battery is None:
            return

        # Only trigger if FSM is in an active flight state
        active_states = {FlightState.EXPLORING, FlightState.INVESTIGATING, FlightState.TAKEOFF, FlightState.RETURNING}
        if self._fsm.state not in active_states:
            return

        if battery <= self._land_threshold:
            logging.getLogger(__name__).warning(
                "battery critical (%d%%) — forcing LANDING", battery
            )
            await self._bus.publish(
                "drone.battery_warning",
                {
                    "level": "critical",
                    "battery": battery,
                    "action": "landing",
                    "timestamp": time(),
                },
            )
            try:
                await self._fsm.transition(FlightState.LANDING)
            except InvalidTransition:
                pass  # already transitioning
        elif battery <= self._rtl_threshold:
            if self._fsm.state != FlightState.RETURNING:
                logging.getLogger(__name__).warning(
                    "battery low (%d%%) — forcing RETURNING", battery
                )
                await self._bus.publish(
                    "drone.battery_warning",
                    {
                        "level": "low",
                        "battery": battery,
                        "action": "returning",
                        "timestamp": time(),
                    },
                )
                try:
                    await self._fsm.transition(FlightState.RETURNING)
                except InvalidTransition:
                    pass
