"""Tests for the building report schema."""

import json

import pytest
from pydantic import ValidationError

from breacheye.report import (
    BuildingReport,
    FlightSummary,
    RoomSummary,
    ThreatSummary,
)


def _make_flight() -> FlightSummary:
    return FlightSummary(
        run_id="run-001",
        start_time=1746200000.0,
        end_time=1746200120.0,
        duration_s=120.0,
        frames_processed=3600,
        detections_total=14,
        nav_decisions_total=240,
        distance_estimate_m=45.5,
        battery_start=95,
        battery_end=72,
    )


def _make_threats() -> ThreatSummary:
    return ThreatSummary(
        total_pois=14,
        by_category={"T1-01": 3, "T2-02": 2, "ROOM": 9},
        by_threat_level={"HOT": 1, "WARM": 4, "CLEAR": 9},
        high_priority_items=[
            {
                "id": "det-001",
                "label": "Armed individual",
                "threat_level": "HOT",
                "location": "room-2",
            }
        ],
    )


def test_room_summary_construction() -> None:
    room = RoomSummary(
        room_id="room-1",
        poi_count=3,
        threat_level="WARM",
        coverage_pct=87.5,
        entry_points=["door-north", "window-east"],
        dimensions_estimate={"width_m": 4.2, "depth_m": 6.1},
    )

    assert room.room_id == "room-1"
    assert room.poi_count == 3
    assert room.threat_level == "WARM"
    assert room.coverage_pct == 87.5
    assert "door-north" in room.entry_points
    assert room.dimensions_estimate is not None


def test_room_summary_optional_dimensions_defaults_none() -> None:
    room = RoomSummary(
        room_id="room-2",
        poi_count=0,
        threat_level="CLEAR",
        coverage_pct=100.0,
    )

    assert room.dimensions_estimate is None
    assert room.entry_points == []


def test_threat_summary_construction() -> None:
    threats = _make_threats()

    assert threats.total_pois == 14
    assert threats.by_category["T1-01"] == 3
    assert threats.by_threat_level["HOT"] == 1
    assert len(threats.high_priority_items) == 1


def test_flight_summary_construction() -> None:
    flight = _make_flight()

    assert flight.run_id == "run-001"
    assert flight.duration_s == 120.0
    assert flight.battery_start == 95
    assert flight.battery_end == 72


def test_flight_summary_optional_fields_default_none() -> None:
    flight = FlightSummary(
        run_id="run-minimal",
        start_time=1746200000.0,
        end_time=1746200060.0,
        duration_s=60.0,
        frames_processed=0,
        detections_total=0,
        nav_decisions_total=0,
    )

    assert flight.distance_estimate_m is None
    assert flight.battery_start is None
    assert flight.battery_end is None


def test_building_report_construction() -> None:
    report = BuildingReport(
        report_id="rpt-abc123",
        generated_at=1746200200.0,
        flight=_make_flight(),
        rooms=[
            RoomSummary(
                room_id="room-1",
                poi_count=5,
                threat_level="HOT",
                coverage_pct=92.0,
                entry_points=["main-door"],
            ),
            RoomSummary(
                room_id="room-2",
                poi_count=1,
                threat_level="WARM",
                coverage_pct=78.0,
            ),
        ],
        threats=_make_threats(),
        recommended_entry="main-door",
        chokepoints=["hallway-junction-A"],
        narrative="Two rooms assessed. One HOT contact in room-2.",
    )

    assert report.report_id == "rpt-abc123"
    assert len(report.rooms) == 2
    assert report.recommended_entry == "main-door"
    assert "HOT" in report.narrative


def test_building_report_serializes_to_json() -> None:
    report = BuildingReport(
        report_id="rpt-serial",
        generated_at=1746200300.0,
        flight=_make_flight(),
        threats=_make_threats(),
    )

    payload = json.loads(report.model_dump_json())

    assert payload["report_id"] == "rpt-serial"
    assert payload["rooms"] == []
    assert payload["chokepoints"] == []
    assert payload["narrative"] == ""
    assert payload["recommended_entry"] is None
    assert payload["flight"]["run_id"] == "run-001"
    assert payload["threats"]["total_pois"] == 14


def test_building_report_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        BuildingReport(
            report_id="rpt-bad",
            generated_at=1.0,
            flight=_make_flight(),
            threats=_make_threats(),
            unknown_field="oops",
        )


def test_room_summary_rejects_invalid_threat_level() -> None:
    with pytest.raises(ValidationError):
        RoomSummary(
            room_id="x",
            poi_count=0,
            threat_level="UNKNOWN",
            coverage_pct=50.0,
        )


def test_flight_summary_rejects_negative_duration() -> None:
    with pytest.raises(ValidationError):
        FlightSummary(
            run_id="bad",
            start_time=1.0,
            end_time=0.0,
            duration_s=-1.0,
            frames_processed=0,
            detections_total=0,
            nav_decisions_total=0,
        )
