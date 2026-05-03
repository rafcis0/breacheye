from pydantic import ValidationError
import pytest

from breacheye.rafa.schemas import (
    ALLOWED_NAVIGATION_ACTIONS,
    BBox2D,
    DepthOutput,
    Detection,
    DetectionOutput,
    FrameInput,
    NavigationDecision,
    NavigationOutput,
    ObstacleAlert,
)


def test_workplan_detection_example_validates() -> None:
    output = DetectionOutput(
        frame_id=42,
        timestamp=1746201234.567,
        detections=[
            Detection(
                id="det-042-001",
                category="T1-01",
                label="Entry Point",
                description="Wooden door, appears unlocked",
                confidence=0.87,
                bbox_2d=BBox2D(x1=120, y1=80, x2=340, y2=520),
                threat_level="CLEAR",
                detection_model="moondream",
            )
        ],
        processing_ms=23,
    )

    assert output.detections[0].category == "T1-01"


def test_workplan_navigation_example_validates() -> None:
    output = NavigationOutput(
        frame_id=42,
        timestamp=1746201234.567,
        decision=NavigationDecision(
            action="move_forward",
            params={"distance_cm": 50, "speed_cm_s": 30},
            confidence=0.82,
            reasoning="Open corridor ahead, no obstacles within 2m",
            exploration_state="exploring",
        ),
    )

    assert output.decision.action in ALLOWED_NAVIGATION_ACTIONS


def test_frame_requires_jpeg_bytes() -> None:
    with pytest.raises(ValidationError):
        FrameInput(frame_id=1, timestamp=1.0, jpeg_bytes=b"")


def test_depth_rejects_byte_length_mismatch() -> None:
    with pytest.raises(ValidationError):
        DepthOutput(frame_id=1, shape=(2, 2), depth_bytes=b"too-short")


def test_obstacle_alert_validates_clear_path() -> None:
    alert = ObstacleAlert(
        frame_id=10,
        timestamp=1746201234.567,
        min_depth=0.8,
        mean_center_depth=0.75,
        obstacle_detected=False,
        direction_hint="unknown",
        clearance_score=0.94,
    )

    assert alert.obstacle_detected is False
    assert alert.direction_hint == "unknown"
    assert alert.clearance_score == pytest.approx(0.94)


def test_obstacle_alert_validates_obstacle_detected() -> None:
    alert = ObstacleAlert(
        frame_id=11,
        timestamp=1746201234.567,
        min_depth=0.08,
        mean_center_depth=0.12,
        obstacle_detected=True,
        direction_hint="center",
        clearance_score=0.0,
    )

    assert alert.obstacle_detected is True
    assert alert.direction_hint == "center"
    assert alert.min_depth == pytest.approx(0.08)


def test_obstacle_alert_rejects_invalid_direction() -> None:
    with pytest.raises(ValidationError):
        ObstacleAlert(
            frame_id=12,
            timestamp=1746201234.567,
            min_depth=0.1,
            mean_center_depth=0.1,
            obstacle_detected=True,
            direction_hint="diagonal",  # not a valid literal
            clearance_score=0.0,
        )


def test_obstacle_alert_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ObstacleAlert(
            frame_id=13,
            timestamp=1746201234.567,
            min_depth=0.5,
            mean_center_depth=0.5,
            obstacle_detected=False,
            direction_hint="unknown",
            clearance_score=1.0,
            unknown_field="oops",
        )
