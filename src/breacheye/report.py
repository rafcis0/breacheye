"""Building report schema definitions.

Canonical report that captures a full building assessment after a drone
flight.  Consumed by CLI, frontend, and optionally Palantir.
"""

from __future__ import annotations

from pydantic import ConfigDict, BaseModel, Field

from breacheye.rafa.schemas import ThreatLevel


__all__ = [
    "RoomSummary",
    "ThreatSummary",
    "FlightSummary",
    "BuildingReport",
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoomSummary(_StrictModel):
    room_id: str
    poi_count: int = Field(ge=0)
    threat_level: ThreatLevel
    coverage_pct: float = Field(ge=0.0, le=100.0)
    entry_points: list[str] = Field(default_factory=list)
    dimensions_estimate: dict | None = None


class ThreatSummary(_StrictModel):
    total_pois: int = Field(ge=0)
    by_category: dict[str, int] = Field(default_factory=dict)
    by_threat_level: dict[str, int] = Field(default_factory=dict)
    high_priority_items: list[dict] = Field(default_factory=list)


class FlightSummary(_StrictModel):
    run_id: str
    start_time: float
    end_time: float
    duration_s: float = Field(ge=0.0)
    frames_processed: int = Field(ge=0)
    detections_total: int = Field(ge=0)
    nav_decisions_total: int = Field(ge=0)
    distance_estimate_m: float | None = Field(default=None, ge=0.0)
    battery_start: int | None = Field(default=None, ge=0, le=100)
    battery_end: int | None = Field(default=None, ge=0, le=100)


class BuildingReport(_StrictModel):
    report_id: str
    generated_at: float
    flight: FlightSummary
    rooms: list[RoomSummary] = Field(default_factory=list)
    threats: ThreatSummary
    recommended_entry: str | None = None
    chokepoints: list[str] = Field(default_factory=list)
    narrative: str = ""
