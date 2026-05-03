"""Tests for FlightDataAccumulator and FlightRecord."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from breacheye.bus import AsyncEventBus
from breacheye.flight_record import FlightDataAccumulator, FlightRecord
from breacheye.models import DroneTelemetry
from breacheye.report import BuildingReport


def _make_detection_payload(det_id: str, category: str = "T1-01", threat: str = "HOT") -> dict:
    """Build a drone.detections payload dict."""
    return {
        "frame_id": 1,
        "timestamp": 1746200000.0,
        "detections": [
            {
                "id": det_id,
                "category": category,
                "label": "Armed individual",
                "description": "",
                "confidence": 0.92,
                "bbox_2d": {"x1": 10, "y1": 20, "x2": 100, "y2": 200},
                "threat_level": threat,
                "detection_model": "moondream-photon",
            }
        ],
        "processing_ms": 18,
    }


def _make_state_change(from_state: str, to_state: str, ts: float = 1746200000.0) -> dict:
    return {"from_state": from_state, "to_state": to_state, "timestamp": ts}


def _make_telemetry(battery: int) -> DroneTelemetry:
    return DroneTelemetry(battery=battery, connected=True)


async def _make_accumulator() -> tuple[FlightDataAccumulator, AsyncEventBus]:
    bus = AsyncEventBus()
    acc = FlightDataAccumulator(bus, run_id="test-run-001")
    await acc.start()
    return acc, bus


async def test_accumulator_starts_and_stops() -> None:
    acc, _ = await _make_accumulator()
    await acc.stop()
    rec = acc.get_record()
    assert rec.run_id == "test-run-001"


async def test_single_detection_recorded() -> None:
    acc, bus = await _make_accumulator()
    try:
        await bus.publish("drone.detections", _make_detection_payload("det-001"))
        await asyncio.sleep(0.05)
        rec = acc.get_record()
        assert len(rec.detections) == 1
        assert rec.detections[0]["id"] == "det-001"
    finally:
        await acc.stop()


async def test_detection_deduplication_by_id() -> None:
    acc, bus = await _make_accumulator()
    try:
        # Publish same detection id twice — should only count once
        await bus.publish("drone.detections", _make_detection_payload("det-dup"))
        await bus.publish("drone.detections", _make_detection_payload("det-dup"))
        await asyncio.sleep(0.05)
        rec = acc.get_record()
        assert len(rec.detections) == 1
    finally:
        await acc.stop()


async def test_different_detection_ids_both_recorded() -> None:
    acc, bus = await _make_accumulator()
    try:
        await bus.publish("drone.detections", _make_detection_payload("det-A"))
        await bus.publish("drone.detections", _make_detection_payload("det-B"))
        await asyncio.sleep(0.05)
        rec = acc.get_record()
        assert len(rec.detections) == 2
    finally:
        await acc.stop()


async def test_poi_summary_counts_by_category() -> None:
    acc, bus = await _make_accumulator()
    try:
        payload = {
            "frame_id": 1,
            "timestamp": 1746200000.0,
            "detections": [
                {
                    "id": "d1",
                    "category": "T1-01",
                    "label": "test",
                    "description": "",
                    "confidence": 0.9,
                    "bbox_2d": {"x1": 0, "y1": 0, "x2": 10, "y2": 10},
                    "threat_level": "HOT",
                    "detection_model": "stub",
                },
                {
                    "id": "d2",
                    "category": "T2-02",
                    "label": "test",
                    "description": "",
                    "confidence": 0.8,
                    "bbox_2d": {"x1": 0, "y1": 0, "x2": 10, "y2": 10},
                    "threat_level": "WARM",
                    "detection_model": "stub",
                },
                {
                    "id": "d3",
                    "category": "T1-01",
                    "label": "test",
                    "description": "",
                    "confidence": 0.7,
                    "bbox_2d": {"x1": 0, "y1": 0, "x2": 10, "y2": 10},
                    "threat_level": "CAUTION",
                    "detection_model": "stub",
                },
            ],
            "processing_ms": 20,
        }
        await bus.publish("drone.detections", payload)
        await asyncio.sleep(0.05)
        rec = acc.get_record()
        assert rec.poi_summary["T1-01"] == 2
        assert rec.poi_summary["T2-02"] == 1
    finally:
        await acc.stop()


async def test_threat_summary_counts_by_level() -> None:
    acc, bus = await _make_accumulator()
    try:
        payload = {
            "frame_id": 1,
            "timestamp": 1746200000.0,
            "detections": [
                {
                    "id": "ta1",
                    "category": "T1-01",
                    "label": "t",
                    "description": "",
                    "confidence": 0.9,
                    "bbox_2d": {"x1": 0, "y1": 0, "x2": 10, "y2": 10},
                    "threat_level": "HOT",
                    "detection_model": "stub",
                },
                {
                    "id": "ta2",
                    "category": "T2-02",
                    "label": "t",
                    "description": "",
                    "confidence": 0.8,
                    "bbox_2d": {"x1": 0, "y1": 0, "x2": 10, "y2": 10},
                    "threat_level": "HOT",
                    "detection_model": "stub",
                },
                {
                    "id": "ta3",
                    "category": "ROOM",
                    "label": "r",
                    "description": "",
                    "confidence": 0.6,
                    "bbox_2d": {"x1": 0, "y1": 0, "x2": 10, "y2": 10},
                    "threat_level": "CLEAR",
                    "detection_model": "stub",
                },
            ],
            "processing_ms": 20,
        }
        await bus.publish("drone.detections", payload)
        await asyncio.sleep(0.05)
        rec = acc.get_record()
        assert rec.threat_summary["HOT"] == 2
        assert rec.threat_summary["CLEAR"] == 1
    finally:
        await acc.stop()


async def test_frames_processed_increments_per_payload() -> None:
    acc, bus = await _make_accumulator()
    try:
        for _ in range(3):
            await bus.publish("drone.detections", _make_detection_payload(str(uuid.uuid4())))
        await asyncio.sleep(0.05)
        rec = acc.get_record()
        assert rec.frames_processed == 3
    finally:
        await acc.stop()


async def test_state_transition_logged() -> None:
    acc, bus = await _make_accumulator()
    try:
        await bus.publish("drone.state_change", _make_state_change("preflight", "takeoff", 1746200001.0))
        await asyncio.sleep(0.05)
        rec = acc.get_record()
        assert len(rec.state_transitions) == 1
        ts, from_s, to_s = rec.state_transitions[0]
        assert ts == 1746200001.0
        assert from_s == "preflight"
        assert to_s == "takeoff"
    finally:
        await acc.stop()


async def test_start_time_set_on_takeoff() -> None:
    acc, bus = await _make_accumulator()
    try:
        await bus.publish("drone.state_change", _make_state_change("preflight", "takeoff", 1746200010.0))
        await asyncio.sleep(0.05)
        rec = acc.get_record()
        assert rec.start_time == 1746200010.0
    finally:
        await acc.stop()


async def test_start_time_not_overwritten_on_second_takeoff() -> None:
    acc, bus = await _make_accumulator()
    try:
        await bus.publish("drone.state_change", _make_state_change("preflight", "takeoff", 1746200010.0))
        await bus.publish("drone.state_change", _make_state_change("preflight", "takeoff", 1746200099.0))
        await asyncio.sleep(0.05)
        rec = acc.get_record()
        assert rec.start_time == 1746200010.0
    finally:
        await acc.stop()


async def test_end_time_set_on_landing() -> None:
    acc, bus = await _make_accumulator()
    try:
        await bus.publish("drone.state_change", _make_state_change("returning", "landing", 1746200120.0))
        await asyncio.sleep(0.05)
        rec = acc.get_record()
        assert rec.end_time == 1746200120.0
    finally:
        await acc.stop()


async def test_end_time_set_on_complete() -> None:
    acc, bus = await _make_accumulator()
    try:
        await bus.publish("drone.state_change", _make_state_change("landing", "complete", 1746200125.0))
        await asyncio.sleep(0.05)
        rec = acc.get_record()
        assert rec.end_time == 1746200125.0
    finally:
        await acc.stop()


async def test_battery_start_and_end_captured() -> None:
    acc, bus = await _make_accumulator()
    try:
        await bus.publish("drone.telemetry", _make_telemetry(95))
        await bus.publish("drone.telemetry", _make_telemetry(88))
        await bus.publish("drone.telemetry", _make_telemetry(74))
        await asyncio.sleep(0.05)
        rec = acc.get_record()
        assert rec.battery_start == 95
        assert rec.battery_end == 74
    finally:
        await acc.stop()


async def test_battery_start_preserved_after_updates() -> None:
    acc, bus = await _make_accumulator()
    try:
        await bus.publish("drone.telemetry", _make_telemetry(100))
        await bus.publish("drone.telemetry", _make_telemetry(50))
        await asyncio.sleep(0.05)
        rec = acc.get_record()
        assert rec.battery_start == 100
        assert rec.battery_end == 50
    finally:
        await acc.stop()


async def test_nav_decisions_counted() -> None:
    acc, bus = await _make_accumulator()
    try:
        for _ in range(5):
            await bus.publish("drone.nav_decision", {"frame_id": 1, "decision": {}})
        await asyncio.sleep(0.05)
        rec = acc.get_record()
        assert rec.nav_decisions == 5
    finally:
        await acc.stop()


async def test_to_building_report_returns_building_report() -> None:
    acc, bus = await _make_accumulator()
    try:
        await bus.publish("drone.state_change", _make_state_change("preflight", "takeoff", 1746200000.0))
        await bus.publish("drone.state_change", _make_state_change("returning", "landing", 1746200120.0))
        await bus.publish("drone.detections", _make_detection_payload("det-r1"))
        await bus.publish("drone.telemetry", _make_telemetry(90))
        await bus.publish("drone.telemetry", _make_telemetry(75))
        await bus.publish("drone.nav_decision", {"frame_id": 1, "decision": {}})
        await asyncio.sleep(0.05)

        report = acc.to_building_report()
        assert isinstance(report, BuildingReport)
        assert report.flight.run_id == "test-run-001"
        assert report.flight.start_time == 1746200000.0
        assert report.flight.end_time == 1746200120.0
        assert report.flight.duration_s == 120.0
        assert report.flight.detections_total == 1
        assert report.flight.nav_decisions_total == 1
        assert report.flight.battery_start == 90
        assert report.flight.battery_end == 75
        assert report.threats.total_pois == 1
        assert report.threats.by_threat_level["HOT"] == 1
    finally:
        await acc.stop()


async def test_to_building_report_serializable() -> None:
    acc, _ = await _make_accumulator()
    try:
        report = acc.to_building_report()
        payload = report.model_dump()
        assert "report_id" in payload
        assert "flight" in payload
        assert "threats" in payload
    finally:
        await acc.stop()


async def test_deduplication_across_multiple_payloads() -> None:
    """Same detection id appearing in two separate payloads counts once."""
    acc, bus = await _make_accumulator()
    try:
        await bus.publish("drone.detections", _make_detection_payload("shared-id"))
        await bus.publish("drone.detections", _make_detection_payload("shared-id"))
        await bus.publish("drone.detections", _make_detection_payload("unique-id"))
        await asyncio.sleep(0.05)
        rec = acc.get_record()
        assert len(rec.detections) == 2
        ids = {d["id"] for d in rec.detections}
        assert ids == {"shared-id", "unique-id"}
    finally:
        await acc.stop()


async def test_get_record_returns_same_instance() -> None:
    acc, _ = await _make_accumulator()
    try:
        r1 = acc.get_record()
        r2 = acc.get_record()
        assert r1 is r2
    finally:
        await acc.stop()
