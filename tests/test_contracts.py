"""
Contract validation tests for BreachEye ZMQ message boundaries.

Validates all Pydantic schemas against the CONSTITUTION contracts.
No ZMQ transport needed — pure schema validation.
Catches schema drift before the H+6 integration checkpoint.
"""

import struct

import pytest
from pydantic import ValidationError

from breacheye.rafa.schemas import (
    BBox2D,
    DepthOutput,
    Detection,
    DetectionOutput,
    ExplorationState,
    FrameInput,
    HealthOutput,
    MemoryStatus,
    ModelStatus,
    NavigationDecision,
    NavigationOutput,
    NavigationAction,
    PoiCategory,
    ThreatLevel,
    Throughput,
)


# ---------------------------------------------------------------------------
# Helpers — valid base objects
# ---------------------------------------------------------------------------

def _valid_bbox() -> dict:
    return {"x1": 10, "y1": 20, "x2": 100, "y2": 200}


def _valid_detection(**overrides) -> dict:
    base = {
        "id": "det-001",
        "category": "T1-01",
        "label": "Door",
        "description": "Wooden door",
        "confidence": 0.85,
        "bbox_2d": _valid_bbox(),
        "threat_level": "CLEAR",
        "detection_model": "moondream",
    }
    base.update(overrides)
    return base


def _valid_depth_bytes(rows: int = 4, cols: int = 4) -> bytes:
    """Return the correct float32 byte payload for a (rows, cols) shape."""
    return struct.pack(f"{rows * cols}f", *[0.5] * (rows * cols))


def _valid_nav_decision(**overrides) -> dict:
    base = {
        "action": "move_forward",
        "params": {"distance_cm": 50},
        "confidence": 0.9,
        "reasoning": "clear corridor",
        "exploration_state": "exploring",
    }
    base.update(overrides)
    return base


def _valid_model_status(**overrides) -> dict:
    base = {"status": "ready"}
    base.update(overrides)
    return base


def _valid_health(**overrides) -> dict:
    base = {
        "pipeline_status": "ready",
        "models_loaded": {"moondream": _valid_model_status()},
        "throughput": {"detection_fps": 20.0, "depth_fps": 30.0, "decision_fps": 10.0},
        "memory": {"ram_used_gb": 4.0, "vram_total_gb": 0.0},
        "errors": [],
        "timestamp": 1746201234.0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. FrameInput
# ---------------------------------------------------------------------------

class TestFrameInput:

    def test_valid_minimal(self):
        frame = FrameInput(frame_id=0, timestamp=1.0, jpeg_bytes=b"\xff\xd8")
        assert frame.frame_id == 0
        assert frame.encoding == "jpeg_bgr_source"
        assert frame.width is None
        assert frame.height is None

    def test_valid_with_optional_dimensions(self):
        frame = FrameInput(
            frame_id=1,
            timestamp=1746201234.5,
            jpeg_bytes=b"\xff\xd8\xff",
            width=960,
            height=720,
        )
        assert frame.width == 960
        assert frame.height == 720

    def test_valid_custom_encoding(self):
        frame = FrameInput(
            frame_id=5,
            timestamp=2.0,
            jpeg_bytes=b"\xff\xd8",
            encoding="jpeg_rgb",
        )
        assert frame.encoding == "jpeg_rgb"

    def test_rejects_missing_jpeg_bytes(self):
        with pytest.raises(ValidationError):
            FrameInput(frame_id=0, timestamp=1.0)

    def test_rejects_empty_jpeg_bytes(self):
        with pytest.raises(ValidationError):
            FrameInput(frame_id=0, timestamp=1.0, jpeg_bytes=b"")

    def test_rejects_negative_frame_id(self):
        with pytest.raises(ValidationError):
            FrameInput(frame_id=-1, timestamp=1.0, jpeg_bytes=b"\xff\xd8")

    def test_rejects_zero_width(self):
        with pytest.raises(ValidationError):
            FrameInput(frame_id=0, timestamp=1.0, jpeg_bytes=b"\xff\xd8", width=0)

    def test_rejects_zero_height(self):
        with pytest.raises(ValidationError):
            FrameInput(frame_id=0, timestamp=1.0, jpeg_bytes=b"\xff\xd8", height=0)

    def test_rejects_negative_width(self):
        with pytest.raises(ValidationError):
            FrameInput(frame_id=0, timestamp=1.0, jpeg_bytes=b"\xff\xd8", width=-1)

    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            FrameInput(
                frame_id=0,
                timestamp=1.0,
                jpeg_bytes=b"\xff\xd8",
                unknown_field="bad",
            )


# ---------------------------------------------------------------------------
# 2. BBox2D
# ---------------------------------------------------------------------------

class TestBBox2D:

    def test_valid_bbox(self):
        bbox = BBox2D(x1=0, y1=0, x2=1, y2=1)
        assert bbox.x1 == 0

    def test_valid_bbox_zero_origin(self):
        bbox = BBox2D(x1=0, y1=0, x2=100, y2=200)
        assert bbox.x2 == 100

    def test_rejects_x2_equal_to_x1(self):
        with pytest.raises(ValidationError):
            BBox2D(x1=50, y1=0, x2=50, y2=100)

    def test_rejects_x2_less_than_x1(self):
        with pytest.raises(ValidationError):
            BBox2D(x1=100, y1=0, x2=50, y2=100)

    def test_rejects_y2_equal_to_y1(self):
        with pytest.raises(ValidationError):
            BBox2D(x1=0, y1=50, x2=100, y2=50)

    def test_rejects_y2_less_than_y1(self):
        with pytest.raises(ValidationError):
            BBox2D(x1=0, y1=100, x2=100, y2=50)

    def test_rejects_negative_x1(self):
        with pytest.raises(ValidationError):
            BBox2D(x1=-1, y1=0, x2=100, y2=100)

    def test_rejects_negative_y1(self):
        with pytest.raises(ValidationError):
            BBox2D(x1=0, y1=-1, x2=100, y2=100)

    def test_rejects_negative_x2(self):
        with pytest.raises(ValidationError):
            # x2=-1 is < 0 (ge=0 violated) but also < x1=0 — either way rejected
            BBox2D(x1=0, y1=0, x2=-1, y2=100)

    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            BBox2D(x1=0, y1=0, x2=10, y2=10, z=5)


# ---------------------------------------------------------------------------
# 3. DetectionOutput
# ---------------------------------------------------------------------------

POI_CATEGORIES = ["T1-01", "T1-02", "T1-03", "T2-02", "T2-03", "T3-01", "T4-01", "ROOM"]
THREAT_LEVELS = ["HOT", "WARM", "CAUTION", "CLEAR", "INFO"]


class TestDetectionOutput:

    def test_valid_with_detections(self):
        output = DetectionOutput(
            frame_id=1,
            timestamp=1.0,
            detections=[Detection(**_valid_detection())],
            processing_ms=20,
        )
        assert len(output.detections) == 1

    def test_valid_empty_detections(self):
        output = DetectionOutput(
            frame_id=0,
            timestamp=1.0,
            detections=[],
            processing_ms=0,
        )
        assert output.detections == []

    def test_valid_default_timestamp(self):
        output = DetectionOutput(frame_id=0, processing_ms=5)
        assert output.timestamp > 0

    @pytest.mark.parametrize("category", POI_CATEGORIES)
    def test_accepts_all_poi_categories(self, category: str):
        det = Detection(**_valid_detection(category=category))
        assert det.category == category

    @pytest.mark.parametrize("threat", THREAT_LEVELS)
    def test_accepts_all_threat_levels(self, threat: str):
        det = Detection(**_valid_detection(threat_level=threat))
        assert det.threat_level == threat

    def test_rejects_invalid_category(self):
        with pytest.raises(ValidationError):
            Detection(**_valid_detection(category="T9-99"))

    def test_rejects_confidence_below_zero(self):
        with pytest.raises(ValidationError):
            Detection(**_valid_detection(confidence=-0.01))

    def test_rejects_confidence_above_one(self):
        with pytest.raises(ValidationError):
            Detection(**_valid_detection(confidence=1.001))

    def test_accepts_confidence_boundary_zero(self):
        det = Detection(**_valid_detection(confidence=0.0))
        assert det.confidence == 0.0

    def test_accepts_confidence_boundary_one(self):
        det = Detection(**_valid_detection(confidence=1.0))
        assert det.confidence == 1.0

    def test_rejects_missing_id(self):
        data = _valid_detection()
        del data["id"]
        with pytest.raises(ValidationError):
            Detection(**data)

    def test_rejects_empty_id(self):
        with pytest.raises(ValidationError):
            Detection(**_valid_detection(id=""))

    def test_rejects_missing_label(self):
        data = _valid_detection()
        del data["label"]
        with pytest.raises(ValidationError):
            Detection(**data)

    def test_rejects_empty_label(self):
        with pytest.raises(ValidationError):
            Detection(**_valid_detection(label=""))

    def test_rejects_empty_detection_model(self):
        with pytest.raises(ValidationError):
            Detection(**_valid_detection(detection_model=""))

    def test_rejects_extra_fields_on_detection(self):
        with pytest.raises(ValidationError):
            Detection(**_valid_detection(unknown="extra"))

    def test_rejects_extra_fields_on_detection_output(self):
        with pytest.raises(ValidationError):
            DetectionOutput(
                frame_id=0,
                timestamp=1.0,
                detections=[],
                processing_ms=0,
                extra_field="bad",
            )

    def test_rejects_negative_processing_ms(self):
        with pytest.raises(ValidationError):
            DetectionOutput(frame_id=0, timestamp=1.0, processing_ms=-1)

    def test_rejects_inverted_bbox_in_detection(self):
        bad_bbox = {"x1": 100, "y1": 0, "x2": 50, "y2": 100}
        with pytest.raises(ValidationError):
            Detection(**_valid_detection(bbox_2d=bad_bbox))

    def test_description_defaults_to_empty_string(self):
        data = _valid_detection()
        del data["description"]
        det = Detection(**data)
        assert det.description == ""


# ---------------------------------------------------------------------------
# 4. DepthOutput
# ---------------------------------------------------------------------------

class TestDepthOutput:

    def test_valid_depth_output(self):
        rows, cols = 4, 4
        depth = DepthOutput(
            frame_id=0,
            timestamp=1.0,
            shape=(rows, cols),
            depth_bytes=_valid_depth_bytes(rows, cols),
        )
        assert depth.dtype == "float32"
        assert depth.unit == "relative_0_near_1_far"

    def test_valid_larger_frame(self):
        rows, cols = 720, 960
        depth = DepthOutput(
            frame_id=1,
            timestamp=1.0,
            shape=(rows, cols),
            depth_bytes=_valid_depth_bytes(rows, cols),
        )
        assert depth.shape == (720, 960)

    def test_rejects_wrong_byte_length(self):
        with pytest.raises(ValidationError):
            DepthOutput(
                frame_id=0,
                timestamp=1.0,
                shape=(4, 4),
                depth_bytes=b"tooshort",
            )

    def test_rejects_empty_depth_bytes(self):
        with pytest.raises(ValidationError):
            DepthOutput(
                frame_id=0,
                timestamp=1.0,
                shape=(4, 4),
                depth_bytes=b"",
            )

    def test_rejects_zero_row_dimension(self):
        with pytest.raises(ValidationError):
            DepthOutput(
                frame_id=0,
                timestamp=1.0,
                shape=(0, 4),
                depth_bytes=b"\x00" * 0,
            )

    def test_rejects_zero_col_dimension(self):
        with pytest.raises(ValidationError):
            DepthOutput(
                frame_id=0,
                timestamp=1.0,
                shape=(4, 0),
                depth_bytes=b"\x00" * 0,
            )

    def test_rejects_negative_frame_id(self):
        rows, cols = 2, 2
        with pytest.raises(ValidationError):
            DepthOutput(
                frame_id=-1,
                timestamp=1.0,
                shape=(rows, cols),
                depth_bytes=_valid_depth_bytes(rows, cols),
            )

    def test_rejects_extra_fields(self):
        rows, cols = 2, 2
        with pytest.raises(ValidationError):
            DepthOutput(
                frame_id=0,
                timestamp=1.0,
                shape=(rows, cols),
                depth_bytes=_valid_depth_bytes(rows, cols),
                bogus="field",
            )

    def test_byte_length_must_match_shape_exactly(self):
        """One extra byte beyond float32 payload should fail."""
        rows, cols = 2, 2
        correct = _valid_depth_bytes(rows, cols)
        with pytest.raises(ValidationError):
            DepthOutput(
                frame_id=0,
                timestamp=1.0,
                shape=(rows, cols),
                depth_bytes=correct + b"\x00",
            )


# ---------------------------------------------------------------------------
# 5. NavigationOutput
# ---------------------------------------------------------------------------

NAVIGATION_ACTIONS = [
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

EXPLORATION_STATES = [
    "exploring",
    "investigating_poi",
    "returning",
    "obstacle_avoidance",
    "coverage_complete",
    "low_battery",
]


class TestNavigationOutput:

    def test_valid_navigation_output(self):
        output = NavigationOutput(
            frame_id=0,
            timestamp=1.0,
            decision=NavigationDecision(**_valid_nav_decision()),
        )
        assert output.decision.action == "move_forward"

    def test_valid_default_timestamp(self):
        output = NavigationOutput(
            frame_id=0,
            decision=NavigationDecision(**_valid_nav_decision()),
        )
        assert output.timestamp > 0

    @pytest.mark.parametrize("action", NAVIGATION_ACTIONS)
    def test_accepts_all_navigation_actions(self, action: str):
        dec = NavigationDecision(**_valid_nav_decision(action=action))
        assert dec.action == action

    @pytest.mark.parametrize("state", EXPLORATION_STATES)
    def test_accepts_all_exploration_states(self, state: str):
        dec = NavigationDecision(**_valid_nav_decision(exploration_state=state))
        assert dec.exploration_state == state

    def test_rejects_invalid_action(self):
        with pytest.raises(ValidationError):
            NavigationDecision(**_valid_nav_decision(action="teleport"))

    def test_rejects_invalid_exploration_state(self):
        with pytest.raises(ValidationError):
            NavigationDecision(**_valid_nav_decision(exploration_state="idle"))

    def test_rejects_confidence_above_one(self):
        with pytest.raises(ValidationError):
            NavigationDecision(**_valid_nav_decision(confidence=1.1))

    def test_rejects_confidence_below_zero(self):
        with pytest.raises(ValidationError):
            NavigationDecision(**_valid_nav_decision(confidence=-0.1))

    def test_accepts_confidence_boundaries(self):
        low = NavigationDecision(**_valid_nav_decision(confidence=0.0))
        high = NavigationDecision(**_valid_nav_decision(confidence=1.0))
        assert low.confidence == 0.0
        assert high.confidence == 1.0

    def test_rejects_extra_fields_on_decision(self):
        with pytest.raises(ValidationError):
            NavigationDecision(**_valid_nav_decision(bogus="field"))

    def test_rejects_extra_fields_on_output(self):
        with pytest.raises(ValidationError):
            NavigationOutput(
                frame_id=0,
                timestamp=1.0,
                decision=NavigationDecision(**_valid_nav_decision()),
                extra="bad",
            )

    def test_params_defaults_to_empty_dict(self):
        data = _valid_nav_decision()
        del data["params"]
        dec = NavigationDecision(**data)
        assert dec.params == {}

    def test_reasoning_defaults_to_empty_string(self):
        data = _valid_nav_decision()
        del data["reasoning"]
        dec = NavigationDecision(**data)
        assert dec.reasoning == ""

    def test_exploration_state_defaults_to_exploring(self):
        data = _valid_nav_decision()
        del data["exploration_state"]
        dec = NavigationDecision(**data)
        assert dec.exploration_state == "exploring"


# ---------------------------------------------------------------------------
# 6. HealthOutput
# ---------------------------------------------------------------------------

PIPELINE_STATUSES = ["starting", "ready", "degraded", "error"]
MODEL_STATUSES = ["ready", "stub", "fallback", "error", "unavailable"]


class TestHealthOutput:

    def test_valid_health_output(self):
        health = HealthOutput(**_valid_health())
        assert health.pipeline_status == "ready"

    def test_valid_empty_models_dict(self):
        health = HealthOutput(**_valid_health(models_loaded={}))
        assert health.models_loaded == {}

    def test_valid_multiple_models(self):
        health = HealthOutput(
            **_valid_health(
                models_loaded={
                    "moondream": _valid_model_status(status="ready"),
                    "depth": _valid_model_status(status="stub"),
                    "qwen": _valid_model_status(status="unavailable"),
                }
            )
        )
        assert len(health.models_loaded) == 3

    @pytest.mark.parametrize("status", PIPELINE_STATUSES)
    def test_accepts_all_pipeline_statuses(self, status: str):
        health = HealthOutput(**_valid_health(pipeline_status=status))
        assert health.pipeline_status == status

    @pytest.mark.parametrize("status", MODEL_STATUSES)
    def test_accepts_all_model_statuses(self, status: str):
        ms = ModelStatus(**_valid_model_status(status=status))
        assert ms.status == status

    def test_rejects_invalid_pipeline_status(self):
        with pytest.raises(ValidationError):
            HealthOutput(**_valid_health(pipeline_status="offline"))

    def test_rejects_invalid_model_status(self):
        with pytest.raises(ValidationError):
            ModelStatus(status="initializing")

    def test_rejects_negative_vram_mb(self):
        with pytest.raises(ValidationError):
            ModelStatus(status="ready", vram_mb=-1)

    def test_rejects_negative_detection_fps(self):
        with pytest.raises(ValidationError):
            Throughput(detection_fps=-1.0)

    def test_rejects_negative_depth_fps(self):
        with pytest.raises(ValidationError):
            Throughput(depth_fps=-0.1)

    def test_rejects_negative_decision_fps(self):
        with pytest.raises(ValidationError):
            Throughput(decision_fps=-5.0)

    def test_accepts_zero_fps(self):
        t = Throughput(detection_fps=0.0, depth_fps=0.0, decision_fps=0.0)
        assert t.detection_fps == 0.0

    def test_rejects_negative_ram_used_gb(self):
        with pytest.raises(ValidationError):
            MemoryStatus(ram_used_gb=-0.1)

    def test_rejects_negative_vram_total_gb(self):
        with pytest.raises(ValidationError):
            MemoryStatus(vram_total_gb=-1.0)

    def test_memory_fields_default_to_none(self):
        mem = MemoryStatus()
        assert mem.ram_used_gb is None
        assert mem.vram_total_gb is None

    def test_model_status_optional_fields_default_to_none(self):
        ms = ModelStatus(status="ready")
        assert ms.active is None
        assert ms.vram_mb is None
        assert ms.error is None

    def test_health_errors_defaults_to_empty_list(self):
        health = HealthOutput(
            pipeline_status="ready",
            models_loaded={},
        )
        assert health.errors == []

    def test_rejects_extra_fields_on_health(self):
        with pytest.raises(ValidationError):
            HealthOutput(**_valid_health(unknown="field"))

    def test_rejects_extra_fields_on_model_status(self):
        with pytest.raises(ValidationError):
            ModelStatus(status="ready", extra="bad")
