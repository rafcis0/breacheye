from __future__ import annotations

import asyncio

from breacheye.adapters.sim import SimAdapter
from breacheye.bus import AsyncEventBus
from breacheye.exploration_tracker import ExplorationTracker
from breacheye.state_machine import FlightState, FlightStateMachine


async def _tracker() -> tuple[ExplorationTracker, AsyncEventBus]:
    adapter = SimAdapter()
    adapter.state.connected = True
    adapter.state.battery = 100
    bus = AsyncEventBus()
    fsm = FlightStateMachine(adapter, bus)
    await adapter.connect()
    await fsm.transition(FlightState.TAKEOFF)
    await fsm.transition(FlightState.EXPLORING)
    return ExplorationTracker(fsm, bus), bus


async def test_doorway_transit_complete_creates_room_graph() -> None:
    tracker, bus = await _tracker()
    graph_queue = await bus.subscribe("drone.room_graph")
    await tracker.start()
    try:
        await bus.publish(
            "drone.exploration_event",
            {
                "event": "doorway_transit_complete",
                "doorway_detection_id": "door-1",
                "timestamp": 123.0,
            },
        )
        await asyncio.sleep(0.05)

        graph = tracker.room_graph
        assert list(graph["nodes"]) == ["room-0001", "room-0002"]
        assert graph["nodes"]["room-0001"]["exploration_status"] == "fully_explored"
        assert graph["nodes"]["room-0002"]["entry_doorway_id"] == "door-1"
        assert graph["connections"][0]["from_room_id"] == "room-0001"
        assert graph["connections"][0]["to_room_id"] == "room-0002"
        assert tracker.coverage_stats["room_count"] == 2
        assert tracker.coverage_stats["current_room_id"] == "room-0002"
        assert not graph_queue.empty()
    finally:
        await tracker.stop()
        await bus.unsubscribe("drone.room_graph", graph_queue)


async def test_rotations_without_new_poi_mark_room_fully_explored() -> None:
    tracker, bus = await _tracker()
    await tracker.start()
    try:
        for frame_id in range(4):
            await bus.publish(
                "drone.nav_decision",
                {
                    "frame_id": frame_id,
                    "decision": {
                        "action": "rotate_right",
                        "reasoning": f"scan {frame_id}",
                        "exploration_state": "exploring",
                    },
                },
            )
        await asyncio.sleep(0.05)

        assert tracker.room_graph["nodes"]["room-0001"]["exploration_status"] == "fully_explored"
    finally:
        await tracker.stop()
