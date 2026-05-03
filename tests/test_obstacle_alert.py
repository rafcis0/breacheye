import numpy as np
import pytest
from breacheye.rafa.schemas import DepthOutput, ObstacleAlert
from breacheye.rafa.spatial_context import compute_obstacle_alert


def _make_depth(values: np.ndarray) -> DepthOutput:
    """Create a DepthOutput from a numpy array."""
    h, w = values.shape
    return DepthOutput(
        frame_id=0,
        timestamp=1.0,
        shape=(h, w),
        depth_bytes=values.astype(np.float32).tobytes(),
    )


def test_uniform_clear_depth():
    """All zones far away — not blocked."""
    values = np.full((720, 960), 0.8, dtype=np.float32)
    alert = compute_obstacle_alert(_make_depth(values), frame_id=1, threshold=0.45)
    assert not alert.blocked
    assert alert.nearest_obstacle_m > 0.45
    assert "left" in alert.zones
    assert "center" in alert.zones
    assert "right" in alert.zones


def test_center_blocked():
    """Center zone has near obstacle — blocked."""
    values = np.full((720, 960), 0.8, dtype=np.float32)
    # Set center third to near
    values[:, 320:640] = 0.1
    alert = compute_obstacle_alert(_make_depth(values), frame_id=2, threshold=0.45)
    assert alert.blocked
    assert alert.zones["center"] < 0.45
    assert alert.zones["left"] > 0.45
    assert alert.zones["right"] > 0.45


def test_left_blocked():
    """Left zone blocked, others clear."""
    values = np.full((720, 960), 0.8, dtype=np.float32)
    values[:, :320] = 0.2
    alert = compute_obstacle_alert(_make_depth(values), frame_id=3, threshold=0.45)
    assert alert.blocked
    assert alert.zones["left"] < 0.45
    assert alert.zones["center"] > 0.45


def test_all_clear_high_threshold():
    """With a very high threshold, even moderate depth triggers blocked."""
    values = np.full((720, 960), 0.5, dtype=np.float32)
    alert = compute_obstacle_alert(_make_depth(values), frame_id=4, threshold=0.9)
    assert alert.blocked


def test_obstacle_alert_schema_validation():
    """Verify ObstacleAlert validates correctly."""
    alert = ObstacleAlert(
        frame_id=0,
        nearest_obstacle_m=0.3,
        zones={"left": 0.6, "center": 0.3, "right": 0.8},
        blocked=True,
        threshold=0.45,
    )
    assert alert.blocked
    assert alert.zones["center"] == 0.3


def test_nearest_is_min_of_zones():
    """nearest_obstacle_m should be the minimum zone score."""
    values = np.full((720, 960), 0.8, dtype=np.float32)
    values[:, :320] = 0.3  # left near
    alert = compute_obstacle_alert(_make_depth(values), frame_id=5, threshold=0.45)
    assert abs(alert.nearest_obstacle_m - min(alert.zones.values())) < 0.01
