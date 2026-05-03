from __future__ import annotations

import asyncio
import logging
from time import time

from breacheye.bus import AsyncEventBus
from breacheye.rafa.schemas import RoomConnection, RoomNode
from breacheye.state_machine import FlightState, FlightStateMachine, InvalidTransition


class ExplorationTracker:
    """Tracks exploration progress from NavigationOutput decisions."""

    def __init__(self, fsm: FlightStateMachine, bus: AsyncEventBus) -> None:
        self._fsm = fsm
        self._bus = bus
        self._areas_visited: set[str] = set()
        self._pois_found: int = 0
        self._last_exploration_state: str = "exploring"
        self._tasks: list[asyncio.Task] = []
        self._queues: dict[str, asyncio.Queue] = {}
        self._room_sequence = 1
        self._current_room_id = "room-0001"
        self._rooms: dict[str, RoomNode] = {
            self._current_room_id: RoomNode(id=self._current_room_id),
        }
        self._connections: list[RoomConnection] = []
        self._rotations_without_new_poi = 0
        self._rotation_complete_threshold = 4

    @property
    def coverage_stats(self) -> dict:
        """Expose stats for UI."""
        return {
            "areas_visited": len(self._areas_visited),
            "pois_found": self._pois_found,
            "last_exploration_state": self._last_exploration_state,
            "room_count": len(self._rooms),
            "current_room_id": self._current_room_id,
            "rooms_explored": len(
                [room for room in self._rooms.values() if room.exploration_status == "fully_explored"]
            ),
            "rooms_remaining": len(
                [room for room in self._rooms.values() if room.exploration_status != "fully_explored"]
            ),
            "room_graph": self.room_graph,
        }

    @property
    def room_graph(self) -> dict:
        return {
            "nodes": {room_id: room.model_dump(mode="json") for room_id, room in self._rooms.items()},
            "connections": [connection.model_dump(mode="json") for connection in self._connections],
        }

    def record_poi(self) -> None:
        """Increment POI counter (called externally when detection confirms a POI)."""
        self._pois_found += 1
        room = self._rooms[self._current_room_id]
        room.pois_found += 1
        if room.exploration_status == "exploring":
            room.exploration_status = "partially_explored"
        self._rotations_without_new_poi = 0

    async def start(self) -> None:
        """Subscribe to exploration events on the bus and process them."""
        for topic in ("drone.nav_decision", "drone.exploration_event"):
            queue = await self._bus.subscribe(topic)
            self._queues[topic] = queue
            self._tasks.append(asyncio.create_task(self._process_loop(topic, queue)))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        for topic, queue in self._queues.items():
            await self._bus.unsubscribe(topic, queue)
        self._queues.clear()

    async def _process_loop(self, topic: str, queue: asyncio.Queue) -> None:
        while True:
            try:
                payload = await queue.get()
                if topic == "drone.nav_decision":
                    await self._handle_nav(payload)
                elif topic == "drone.exploration_event":
                    await self._handle_exploration_event(payload)
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
            self._mark_room_area_visited(area_key)

        action = decision.get("action")
        if action in {"rotate_left", "rotate_right"}:
            self._rotations_without_new_poi += 1
            if self._rotations_without_new_poi >= self._rotation_complete_threshold:
                self._mark_current_room_fully_explored()
        elif action not in {None, "hover"}:
            self._rotations_without_new_poi = 0

        if exploration_state == "coverage_complete":
            self._mark_current_room_fully_explored()
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

    async def _handle_exploration_event(self, event: dict) -> None:
        name = event.get("event")
        if name in {"coverage_complete", "room_fully_explored"}:
            self._mark_current_room_fully_explored()
            return
        if name not in {"doorway_transit_complete", "doorway_transit_completed"}:
            return

        doorway_id = str(event.get("doorway_detection_id") or f"doorway-{self._room_sequence:04d}")
        previous_room_id = self._current_room_id
        self._room_sequence += 1
        next_room_id = f"room-{self._room_sequence:04d}"
        self._rooms[previous_room_id].exploration_status = "fully_explored"
        self._rooms[next_room_id] = RoomNode(id=next_room_id, entry_doorway_id=doorway_id)
        self._connections.append(
            RoomConnection(
                doorway_detection_id=doorway_id,
                from_room_id=previous_room_id,
                to_room_id=next_room_id,
                transit_timestamp=float(event.get("timestamp") or time()),
            )
        )
        self._current_room_id = next_room_id
        self._rotations_without_new_poi = 0
        await self._bus.publish(
            "drone.room_graph",
            {
                "event": "room_created",
                "from_room_id": previous_room_id,
                "to_room_id": next_room_id,
                "doorway_detection_id": doorway_id,
                "room_graph": self.room_graph,
                "timestamp": time(),
            },
        )

    def _mark_room_area_visited(self, area_key: str) -> None:
        room = self._rooms[self._current_room_id]
        room.area_visited_count += 1
        if room.exploration_status == "exploring":
            room.exploration_status = "partially_explored"

    def _mark_current_room_fully_explored(self) -> None:
        self._rooms[self._current_room_id].exploration_status = "fully_explored"
