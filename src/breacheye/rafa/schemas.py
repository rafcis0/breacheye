from __future__ import annotations

from time import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


PoiCategory = Literal["T1-01", "T1-02", "T1-03", "T2-02", "T2-03", "T3-01", "T4-01", "ROOM"]
ThreatLevel = Literal["HOT", "WARM", "CAUTION", "CLEAR", "INFO"]
ObstacleDirection = Literal["center", "left", "right", "unknown"]
NavigationAction = Literal[
    "move_forward",
    "move_back",
    "move_left",
    "move_right",
    "move_up",
    "move_down",
    "rotate_left",
    "rotate_right",
    "hover",
    "land",
]
ExplorationState = Literal[
    "exploring",
    "investigating_poi",
    "returning",
    "obstacle_avoidance",
    "coverage_complete",
    "low_battery",
]

ALLOWED_NAVIGATION_ACTIONS: set[str] = {
    "move_forward",
    "move_back",
    "move_left",
    "move_right",
    "move_up",
    "move_down",
    "rotate_left",
    "rotate_right",
    "hover",
    "land",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FrameInput(StrictModel):
    frame_id: int = Field(ge=0)
    timestamp: float
    jpeg_bytes: bytes = Field(min_length=1)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    encoding: str = "jpeg_bgr_source"


class BBox2D(StrictModel):
    x1: int = Field(ge=0)
    y1: int = Field(ge=0)
    x2: int = Field(ge=0)
    y2: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_order(self) -> "BBox2D":
        if self.x2 <= self.x1:
            raise ValueError("bbox_2d.x2 must be greater than x1")
        if self.y2 <= self.y1:
            raise ValueError("bbox_2d.y2 must be greater than y1")
        return self


class Detection(StrictModel):
    id: str = Field(min_length=1)
    category: PoiCategory
    label: str = Field(min_length=1)
    description: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    bbox_2d: BBox2D
    threat_level: ThreatLevel
    detection_model: str = Field(min_length=1)


class DetectionOutput(StrictModel):
    frame_id: int = Field(ge=0)
    timestamp: float = Field(default_factory=time)
    detections: list[Detection] = Field(default_factory=list)
    processing_ms: int = Field(ge=0)


class DepthOutput(StrictModel):
    frame_id: int = Field(ge=0)
    timestamp: float = Field(default_factory=time)
    shape: tuple[int, int]
    dtype: Literal["float32"] = "float32"
    unit: Literal["relative_0_near_1_far"] = "relative_0_near_1_far"
    depth_bytes: bytes = Field(min_length=1)

    @field_validator("shape")
    @classmethod
    def validate_shape(cls, value: tuple[int, int]) -> tuple[int, int]:
        if len(value) != 2 or value[0] <= 0 or value[1] <= 0:
            raise ValueError("shape must be two positive integers")
        return value

    @model_validator(mode="after")
    def validate_byte_length(self) -> "DepthOutput":
        expected = self.shape[0] * self.shape[1] * 4
        if len(self.depth_bytes) != expected:
            raise ValueError("depth_bytes length does not match float32 shape")
        return self


class ObstacleAlert(StrictModel):
    frame_id: int = Field(ge=0)
    timestamp: float = Field(default_factory=time)
    min_depth: float = Field(ge=0.0, le=1.0)
    mean_center_depth: float = Field(ge=0.0, le=1.0)
    obstacle_detected: bool
    direction_hint: ObstacleDirection
    clearance_score: float = Field(ge=0.0, le=1.0)


class NavigationDecision(StrictModel):
    action: NavigationAction
    params: dict[str, int | float | str] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = ""
    exploration_state: ExplorationState = "exploring"


class NavigationOutput(StrictModel):
    frame_id: int = Field(ge=0)
    timestamp: float = Field(default_factory=time)
    decision: NavigationDecision


class MapPose(StrictModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    yaw_deg: float = 0.0
    source: str = "unknown"


class LookingAt(StrictModel):
    direction_label: str = "unknown"
    nearest_obstacle_m: float | None = Field(default=None, ge=0.0)
    visible_region: str = "unknown"


class MapFrontier(StrictModel):
    id: str = Field(min_length=1)
    bearing_deg: float
    distance_m: float | None = Field(default=None, ge=0.0)
    label: str = Field(min_length=1)


class MapObject(StrictModel):
    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    relative_position: str = "unknown"
    confidence: float = Field(ge=0.0, le=1.0)


class SpatialNavigationContext(StrictModel):
    frame_id: int = Field(ge=0)
    current_pose: MapPose = Field(default_factory=MapPose)
    looking_at: LookingAt = Field(default_factory=LookingAt)
    visited: list[str] = Field(default_factory=list)
    unexplored_frontiers: list[MapFrontier] = Field(default_factory=list)
    known_objects: list[MapObject] = Field(default_factory=list)
    recent_actions: list[NavigationAction] = Field(default_factory=list)
    allowed_actions: list[NavigationAction] = Field(
        default_factory=lambda: ["hover", "move_forward", "rotate_left", "rotate_right"]
    )
    obstacle_alert: ObstacleAlert | None = None
    source: str = "stub"


class ModelStatus(StrictModel):
    status: Literal["ready", "stub", "fallback", "error", "unavailable"]
    active: str | None = None
    vram_mb: int | None = Field(default=None, ge=0)
    error: str | None = None


class Throughput(StrictModel):
    detection_fps: float = Field(default=0.0, ge=0.0)
    depth_fps: float = Field(default=0.0, ge=0.0)
    decision_fps: float = Field(default=0.0, ge=0.0)


class MemoryStatus(StrictModel):
    ram_used_gb: float | None = Field(default=None, ge=0.0)
    vram_total_gb: float | None = Field(default=None, ge=0.0)


class HealthOutput(StrictModel):
    pipeline_status: Literal["starting", "ready", "degraded", "error"] = "ready"
    models_loaded: dict[str, ModelStatus]
    throughput: Throughput = Field(default_factory=Throughput)
    memory: MemoryStatus = Field(default_factory=MemoryStatus)
    errors: list[str] = Field(default_factory=list)
    timestamp: float = Field(default_factory=time)


class ObstacleAlert(StrictModel):
    frame_id: int = Field(ge=0)
    timestamp: float = Field(default_factory=time)
    nearest_obstacle_m: float = Field(ge=0.0, le=1.0)
    zones: dict[str, float]
    blocked: bool
    threshold: float = Field(ge=0.0, le=1.0)
