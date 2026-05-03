"""Tests for the post-flight building report generator."""

from __future__ import annotations

import pytest

from breacheye.report import BuildingReport, FlightSummary, RoomSummary, ThreatSummary
from breacheye.report_generator import ReportGenerator


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def _make_flight(
    *,
    run_id: str = "run-test-001",
    start_time: float = 1746200000.0,
    end_time: float = 1746200120.0,
    duration_s: float = 120.0,
    frames_processed: int = 3600,
    detections_total: int = 14,
    nav_decisions_total: int = 240,
    battery_start: int | None = 95,
    battery_end: int | None = 72,
) -> FlightSummary:
    return FlightSummary(
        run_id=run_id,
        start_time=start_time,
        end_time=end_time,
        duration_s=duration_s,
        frames_processed=frames_processed,
        detections_total=detections_total,
        nav_decisions_total=nav_decisions_total,
        battery_start=battery_start,
        battery_end=battery_end,
    )


def _make_threats(
    *,
    total_pois: int = 14,
    by_category: dict | None = None,
    by_threat_level: dict | None = None,
    high_priority_items: list | None = None,
) -> ThreatSummary:
    return ThreatSummary(
        total_pois=total_pois,
        by_category=by_category or {"T1-01": 3, "T2-02": 2, "ROOM": 9},
        by_threat_level=by_threat_level or {"HOT": 1, "WARM": 4, "CLEAR": 9},
        high_priority_items=high_priority_items
        or [
            {
                "id": "det-001",
                "label": "Armed individual",
                "threat_level": "HOT",
                "location": "room-2",
            }
        ],
    )


_SENTINEL = object()


def _make_report(
    *,
    rooms: list[RoomSummary] | object = _SENTINEL,
    recommended_entry: str | None = "main-door",
    chokepoints: list[str] | object = _SENTINEL,
    narrative: str = "",
) -> BuildingReport:
    if rooms is _SENTINEL:
        rooms = [
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
        ]
    if chokepoints is _SENTINEL:
        chokepoints = ["hallway-junction-A"]
    return BuildingReport(
        report_id="rpt-test-abc",
        generated_at=1746200200.0,
        flight=_make_flight(),
        rooms=rooms,  # type: ignore[arg-type]
        threats=_make_threats(),
        recommended_entry=recommended_entry,
        chokepoints=chokepoints,  # type: ignore[arg-type]
        narrative=narrative,
    )


# --------------------------------------------------------------------------- #
# Section presence tests
# --------------------------------------------------------------------------- #


class TestGenerateTextReport:
    def setup_method(self) -> None:
        self.gen = ReportGenerator()

    def test_header_section_present(self) -> None:
        output = self.gen.generate_text_report(_make_report())
        assert "BREACHEYE BUILDING ASSESSMENT REPORT" in output
        assert "rpt-test-abc" in output

    def test_flight_stats_section_present(self) -> None:
        output = self.gen.generate_text_report(_make_report())
        assert "FLIGHT STATS" in output
        assert "run-test-001" in output
        assert "120.0s" in output
        assert "3600" in output
        assert "14" in output
        assert "240" in output

    def test_battery_usage_displayed(self) -> None:
        output = self.gen.generate_text_report(_make_report())
        assert "95%" in output
        assert "72%" in output

    def test_threat_assessment_section_present(self) -> None:
        output = self.gen.generate_text_report(_make_report())
        assert "THREAT ASSESSMENT" in output
        assert "Total POIs" in output
        assert "HOT" in output
        assert "WARM" in output

    def test_high_priority_items_listed(self) -> None:
        output = self.gen.generate_text_report(_make_report())
        assert "Armed individual" in output
        assert "HOT" in output

    def test_room_summary_section_present(self) -> None:
        output = self.gen.generate_text_report(_make_report())
        assert "ROOM SUMMARY" in output
        assert "room-1" in output
        assert "room-2" in output

    def test_room_entry_points_listed(self) -> None:
        output = self.gen.generate_text_report(_make_report())
        assert "main-door" in output

    def test_recommendations_section_present(self) -> None:
        output = self.gen.generate_text_report(_make_report())
        assert "RECOMMENDATIONS" in output
        assert "main-door" in output
        assert "hallway-junction-A" in output

    def test_no_rooms_section_omitted(self) -> None:
        report = _make_report(rooms=[])
        output = self.gen.generate_text_report(report)
        assert "ROOM SUMMARY" not in output

    def test_no_narrative_section_omitted(self) -> None:
        report = _make_report(narrative="")
        output = self.gen.generate_text_report(report)
        assert "NARRATIVE SUMMARY" not in output

    def test_narrative_section_present_when_set(self) -> None:
        report = _make_report(narrative="Alpha team should approach via the north corridor.")
        output = self.gen.generate_text_report(report)
        assert "NARRATIVE SUMMARY" in output
        assert "Alpha team should approach via the north corridor." in output

    def test_no_chokepoints_message(self) -> None:
        report = _make_report(chokepoints=[])
        output = self.gen.generate_text_report(report)
        assert "none identified" in output

    def test_no_recommended_entry_shows_na(self) -> None:
        report = _make_report(recommended_entry=None)
        output = self.gen.generate_text_report(report)
        assert "N/A" in output

    def test_battery_missing_gracefully(self) -> None:
        flight = _make_flight(battery_start=None, battery_end=None)
        report = BuildingReport(
            report_id="rpt-nobatt",
            generated_at=1746200200.0,
            flight=flight,
            threats=_make_threats(),
        )
        output = self.gen.generate_text_report(report)
        assert "FLIGHT STATS" in output
        assert "Battery" not in output

    def test_battery_start_only(self) -> None:
        flight = _make_flight(battery_start=80, battery_end=None)
        report = BuildingReport(
            report_id="rpt-startonly",
            generated_at=1746200200.0,
            flight=flight,
            threats=_make_threats(),
        )
        output = self.gen.generate_text_report(report)
        assert "80%" in output

    def test_distance_estimate_displayed(self) -> None:
        flight = FlightSummary(
            run_id="run-x",
            start_time=1746200000.0,
            end_time=1746200060.0,
            duration_s=60.0,
            frames_processed=100,
            detections_total=0,
            nav_decisions_total=10,
            distance_estimate_m=12.5,
        )
        report = BuildingReport(
            report_id="rpt-dist",
            generated_at=1746200200.0,
            flight=flight,
            threats=ThreatSummary(total_pois=0),
        )
        output = self.gen.generate_text_report(report)
        assert "12.5" in output

    def test_output_is_string(self) -> None:
        output = self.gen.generate_text_report(_make_report())
        assert isinstance(output, str)
        assert len(output) > 0


# --------------------------------------------------------------------------- #
# Fallback narrative tests
# --------------------------------------------------------------------------- #


class TestFallbackNarrative:
    def setup_method(self) -> None:
        self.gen = ReportGenerator()

    def test_fallback_contains_run_id(self) -> None:
        report = _make_report()
        narrative = self.gen._fallback_narrative(report)
        assert "run-test-001" in narrative

    def test_fallback_mentions_hot_threats(self) -> None:
        report = _make_report()
        narrative = self.gen._fallback_narrative(report)
        assert "HOT" in narrative

    def test_fallback_no_threats_message(self) -> None:
        report = BuildingReport(
            report_id="rpt-safe",
            generated_at=1746200200.0,
            flight=_make_flight(detections_total=0),
            threats=ThreatSummary(
                total_pois=0,
                by_threat_level={"CLEAR": 5},
            ),
        )
        narrative = self.gen._fallback_narrative(report)
        assert "No high-priority threats" in narrative

    def test_fallback_warm_only_message(self) -> None:
        report = BuildingReport(
            report_id="rpt-warm",
            generated_at=1746200200.0,
            flight=_make_flight(detections_total=3),
            threats=ThreatSummary(
                total_pois=3,
                by_threat_level={"WARM": 3},
            ),
        )
        narrative = self.gen._fallback_narrative(report)
        assert "WARM" in narrative

    def test_fallback_includes_recommended_entry(self) -> None:
        report = _make_report(recommended_entry="back-door")
        narrative = self.gen._fallback_narrative(report)
        assert "back-door" in narrative

    def test_fallback_includes_chokepoints(self) -> None:
        report = _make_report(
            recommended_entry=None,
            chokepoints=["stairwell-B"],
        )
        narrative = self.gen._fallback_narrative(report)
        assert "stairwell-B" in narrative

    def test_fallback_room_count_included(self) -> None:
        report = _make_report()
        narrative = self.gen._fallback_narrative(report)
        assert "2" in narrative or "two" in narrative.lower() or "area" in narrative

    def test_fallback_returns_string(self) -> None:
        narrative = self.gen._fallback_narrative(_make_report())
        assert isinstance(narrative, str)
        assert len(narrative) > 0


# --------------------------------------------------------------------------- #
# Async narrative tests (no Qwen available -> uses fallback)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_generate_narrative_without_qwen_uses_fallback() -> None:
    """With no BREACHEYE_QWEN_SERVER_URL set, narrative falls back to rule-based."""
    import os

    gen = ReportGenerator()
    report = _make_report()

    # Ensure env var is not set
    os.environ.pop("BREACHEYE_QWEN_SERVER_URL", None)

    narrative = await gen.generate_narrative(report)

    assert isinstance(narrative, str)
    assert len(narrative) > 0
    # Must contain content derived from the report data
    assert "run-test-001" in narrative or "HOT" in narrative or "14" in narrative
