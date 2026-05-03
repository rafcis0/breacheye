"""Flight data accumulator for post-flight report generation.

Subscribes to bus events during flight and builds a structured flight record.
Runs alongside ExplorationTracker but serves a different purpose — preserving
the full record for post-flight synthesis.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from time import time

from breacheye.bus import AsyncEventBus
from breacheye.report import BuildingReport, FlightSummary, ThreatSummary

log = logging.getLogger(__name__)

_TOPICS = [
    "drone.detections",
    "drone.state_change",
    "drone.telemetry",
    "drone.nav_decision",
]

# State names that mark flight start/end
_TAKEOFF_STATE = "takeoff"
_LANDING_STATES = {"landing", "complete"}


@dataclass
class FlightRecord:
    run_id: str
    start_time: float | None = None
    end_time: float | None = None
    detections: list[dict] = field(default_factory=list)
    poi_summary: dict[str, int] = field(default_factory=dict)
    threat_summary: dict[str, int] = field(default_factory=dict)
    state_transitions: list[tuple[float, str, str]] = field(default_factory=list)
    frames_processed: int = 0
    nav_decisions: int = 0
    battery_start: int | None = None
    battery_end: int | None = None


class FlightDataAccumulator:
    """Accumulates bus events during a flight for post-flight report generation."""

    def __init__(self, bus: AsyncEventBus, run_id: str) -> None:
        self._bus = bus
        self._record = FlightRecord(run_id=run_id)
        self._detection_ids: set[str] = set()
        self._queues: dict[str, asyncio.Queue] = {}
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Subscribe to relevant bus topics and start listening."""
        for topic in _TOPICS:
            self._queues[topic] = await self._bus.subscribe(topic)
        self._task = asyncio.create_task(self._process_loop(), name="flight-data-accumulator")

    async def stop(self) -> None:
        """Unsubscribe from all topics and finalize the record."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        for topic, queue in self._queues.items():
            await self._bus.unsubscribe(topic, queue)
        self._queues.clear()

    def get_record(self) -> FlightRecord:
        """Return the accumulated flight record."""
        return self._record

    def to_building_report(self) -> BuildingReport:
        """Convert the accumulated record to BuildingReport schema.

        Deterministic conversion — no VLM needed. The narrative comes in #79.
        """
        rec = self._record
        now = time()
        start = rec.start_time or now
        end = rec.end_time or now
        duration = max(0.0, end - start)

        flight = FlightSummary(
            run_id=rec.run_id,
            start_time=start,
            end_time=end,
            duration_s=duration,
            frames_processed=rec.frames_processed,
            detections_total=len(rec.detections),
            nav_decisions_total=rec.nav_decisions,
            battery_start=rec.battery_start,
            battery_end=rec.battery_end,
        )

        # Build high-priority items from HOT detections
        high_priority = [
            d for d in rec.detections
            if d.get("threat_level") in ("HOT", "WARM")
        ]

        threats = ThreatSummary(
            total_pois=len(rec.detections),
            by_category=dict(rec.poi_summary),
            by_threat_level=dict(rec.threat_summary),
            high_priority_items=high_priority,
        )

        return BuildingReport(
            report_id=str(uuid.uuid4()),
            generated_at=now,
            flight=flight,
            rooms=[],
            threats=threats,
            narrative="",
        )

    async def _process_loop(self) -> None:
        """Multiplex all topic queues into a single processing loop."""
        pending: set[asyncio.Task] = set()
        # Build initial set of waiter tasks, keyed by topic name
        topic_tasks: dict[asyncio.Task, str] = {}
        for topic, queue in self._queues.items():
            t = asyncio.create_task(queue.get(), name=topic)
            pending.add(t)
            topic_tasks[t] = topic

        try:
            while True:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for t in done:
                    topic = topic_tasks.pop(t)
                    try:
                        message = t.result()
                        await self._dispatch(topic, message)
                    except Exception as exc:
                        log.warning("flight accumulator error on %s: %s", topic, exc)
                    # Re-arm the waiter for this topic
                    new_t = asyncio.create_task(self._queues[topic].get(), name=topic)
                    pending.add(new_t)
                    topic_tasks[new_t] = topic
        except asyncio.CancelledError:
            # Cancel all pending waiters before propagating
            for t in pending:
                t.cancel()
            raise

    async def _dispatch(self, topic: str, message: object) -> None:
        if topic == "drone.detections":
            self._handle_detections(message)
        elif topic == "drone.state_change":
            self._handle_state_change(message)
        elif topic == "drone.telemetry":
            self._handle_telemetry(message)
        elif topic == "drone.nav_decision":
            self._handle_nav_decision(message)

    def _handle_detections(self, message: object) -> None:
        """Extract detections from payload, deduplicate by id, count POIs and threats."""
        if isinstance(message, dict):
            raw_detections = message.get("detections", [])
        elif hasattr(message, "detections"):
            raw_detections = message.detections  # type: ignore[union-attr]
        else:
            return

        # Count frames processed (one DetectionOutput per frame)
        self._record.frames_processed += 1

        for det in raw_detections:
            if isinstance(det, dict):
                det_id = det.get("id", "")
                category = det.get("category", "")
                threat = det.get("threat_level", "")
            elif hasattr(det, "id"):
                # Handle Pydantic model objects
                det_id = det.id  # type: ignore[union-attr]
                category = str(det.category) if hasattr(det, "category") else ""  # type: ignore[union-attr]
                threat = str(det.threat_level) if hasattr(det, "threat_level") else ""  # type: ignore[union-attr]
                det = det.model_dump() if hasattr(det, "model_dump") else {}
            else:
                continue

            if not det_id or det_id in self._detection_ids:
                continue

            self._detection_ids.add(det_id)
            self._record.detections.append(det if isinstance(det, dict) else {})

            if category:
                self._record.poi_summary[category] = (
                    self._record.poi_summary.get(category, 0) + 1
                )
            if threat:
                self._record.threat_summary[threat] = (
                    self._record.threat_summary.get(threat, 0) + 1
                )

    def _handle_state_change(self, message: object) -> None:
        """Log state transitions; capture start/end times on TAKEOFF/LANDING."""
        if not isinstance(message, dict):
            return

        from_state = str(message.get("from_state", ""))
        to_state = str(message.get("to_state", ""))
        ts = float(message.get("timestamp", time()))

        self._record.state_transitions.append((ts, from_state, to_state))

        if to_state == _TAKEOFF_STATE and self._record.start_time is None:
            self._record.start_time = ts
        elif to_state in _LANDING_STATES and self._record.end_time is None:
            self._record.end_time = ts

    def _handle_telemetry(self, message: object) -> None:
        """Capture battery level — first reading as start, latest as end."""
        if isinstance(message, dict):
            battery = message.get("battery")
        elif hasattr(message, "battery"):
            battery = message.battery  # type: ignore[union-attr]
        else:
            return

        if not isinstance(battery, int):
            return

        if self._record.battery_start is None:
            self._record.battery_start = battery
        self._record.battery_end = battery

    def _handle_nav_decision(self, _message: object) -> None:
        """Increment nav decision counter."""
        self._record.nav_decisions += 1
