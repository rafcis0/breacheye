import os
import numpy as np
import pytest
from breacheye.rafa.schemas import DepthOutput
from breacheye.rafa.spatial_context import (
    CLEARANCE_PRESETS,
    AdaptiveThreshold,
    resolve_clearance_threshold,
    render_depth_zones,
)

try:
    import cv2 as _cv2  # noqa: F401
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False

cv2_required = pytest.mark.skipif(not _CV2_AVAILABLE, reason="cv2 not available")


def _make_depth(values: np.ndarray) -> DepthOutput:
    h, w = values.shape
    return DepthOutput(
        frame_id=0, timestamp=1.0, shape=(h, w),
        depth_bytes=values.astype(np.float32).tobytes(),
    )


# --- P0: Preset tests ---

def test_default_threshold():
    """No env vars set → default 0.45."""
    os.environ.pop("BREACHEYE_NAV_CLEARANCE_PRESET", None)
    os.environ.pop("BREACHEYE_NAV_MIN_FORWARD_CLEARANCE_M", None)
    assert resolve_clearance_threshold() == 0.45


def test_preset_tight(monkeypatch):
    monkeypatch.setenv("BREACHEYE_NAV_CLEARANCE_PRESET", "tight")
    monkeypatch.delenv("BREACHEYE_NAV_MIN_FORWARD_CLEARANCE_M", raising=False)
    assert resolve_clearance_threshold() == 0.25


def test_preset_normal(monkeypatch):
    monkeypatch.setenv("BREACHEYE_NAV_CLEARANCE_PRESET", "normal")
    assert resolve_clearance_threshold() == 0.45


def test_preset_wide(monkeypatch):
    monkeypatch.setenv("BREACHEYE_NAV_CLEARANCE_PRESET", "wide")
    assert resolve_clearance_threshold() == 0.65


def test_explicit_overrides_preset(monkeypatch):
    monkeypatch.setenv("BREACHEYE_NAV_CLEARANCE_PRESET", "wide")
    assert resolve_clearance_threshold(0.30) == 0.30


def test_env_var_overrides_default(monkeypatch):
    monkeypatch.delenv("BREACHEYE_NAV_CLEARANCE_PRESET", raising=False)
    monkeypatch.setenv("BREACHEYE_NAV_MIN_FORWARD_CLEARANCE_M", "0.55")
    assert resolve_clearance_threshold() == 0.55


def test_preset_takes_priority_over_env_var(monkeypatch):
    monkeypatch.setenv("BREACHEYE_NAV_CLEARANCE_PRESET", "tight")
    monkeypatch.setenv("BREACHEYE_NAV_MIN_FORWARD_CLEARANCE_M", "0.99")
    assert resolve_clearance_threshold() == 0.25


def test_unknown_preset_falls_through(monkeypatch):
    monkeypatch.setenv("BREACHEYE_NAV_CLEARANCE_PRESET", "nonexistent")
    monkeypatch.setenv("BREACHEYE_NAV_MIN_FORWARD_CLEARANCE_M", "0.55")
    assert resolve_clearance_threshold() == 0.55


def test_value_clamped():
    assert resolve_clearance_threshold(5.0) == 1.0
    assert resolve_clearance_threshold(-1.0) == 0.0


# --- P1: Adaptive tests ---

def test_adaptive_starts_at_base():
    adaptive = AdaptiveThreshold()
    assert adaptive.threshold == resolve_clearance_threshold()


def test_adaptive_tightens_in_small_room():
    """Low median depth → tight threshold after hysteresis."""
    adaptive = AdaptiveThreshold(window_size=10, hysteresis=3)
    values = np.full((100, 100), 0.2, dtype=np.float32)  # near
    depth = _make_depth(values)
    for _ in range(5):
        adaptive.update(depth)
    assert adaptive.threshold == CLEARANCE_PRESETS["tight"]


def test_adaptive_widens_in_open_space():
    """High median depth → wide threshold after hysteresis."""
    adaptive = AdaptiveThreshold(window_size=10, hysteresis=3)
    values = np.full((100, 100), 0.8, dtype=np.float32)  # far
    depth = _make_depth(values)
    for _ in range(5):
        adaptive.update(depth)
    assert adaptive.threshold == CLEARANCE_PRESETS["wide"]


def test_adaptive_requires_hysteresis():
    """Threshold doesn't change until hysteresis count met."""
    adaptive = AdaptiveThreshold(window_size=10, hysteresis=5)
    base = adaptive.threshold
    values = np.full((100, 100), 0.2, dtype=np.float32)
    depth = _make_depth(values)
    # Feed 3 frames (less than hysteresis of 5)
    for _ in range(3):
        adaptive.update(depth)
    assert adaptive.threshold == base  # hasn't switched yet


def test_adaptive_handles_mixed_input():
    """Alternating near/far doesn't trigger switch (no agreement)."""
    adaptive = AdaptiveThreshold(window_size=10, hysteresis=3)
    base = adaptive.threshold
    near = _make_depth(np.full((100, 100), 0.1, dtype=np.float32))
    far = _make_depth(np.full((100, 100), 0.9, dtype=np.float32))
    for _ in range(10):
        adaptive.update(near)
        adaptive.update(far)
    # Rolling median is ~0.5 → "normal", but hysteresis may not be met due to alternation
    # The key assertion: it didn't swing to an extreme
    assert adaptive.threshold in (CLEARANCE_PRESETS["normal"], base)


# --- P2: Visualization tests ---

@cv2_required
def test_render_depth_zones_returns_jpeg():
    """Verify render produces valid JPEG bytes."""
    values = np.full((720, 960), 0.5, dtype=np.float32)
    jpeg = render_depth_zones(_make_depth(values), threshold=0.45)
    assert isinstance(jpeg, bytes)
    assert len(jpeg) > 100
    assert jpeg[:2] == b'\xff\xd8'  # JPEG magic bytes


@cv2_required
def test_render_depth_zones_with_blocked_center():
    """Visualization with blocked center zone produces valid output."""
    values = np.full((720, 960), 0.8, dtype=np.float32)
    values[:, 320:640] = 0.1
    jpeg = render_depth_zones(_make_depth(values), threshold=0.45)
    assert isinstance(jpeg, bytes)
    assert jpeg[:2] == b'\xff\xd8'
