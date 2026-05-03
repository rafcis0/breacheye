from __future__ import annotations

import asyncio

import pytest

from breacheye.adapters.sim import SimAdapter
from breacheye.bus import AsyncEventBus
from breacheye.models import CommandType, DroneCommand, DroneTelemetry
from breacheye.safety import SafetyController
from breacheye.stabilizer import (
    FlightStabilizer,
    MotionEstimate,
    StabilizerConfig,
    _left_right_correction,
    _safety_guard_reasons,
    _telemetry_guard,
    estimate_motion,
)
from breacheye.video import FrameStore, encode_jpeg


def _shifted_frames():
    import cv2
    import numpy as np

    base = np.zeros((120, 160, 3), dtype=np.uint8)
    for x in range(20, 150, 30):
        for y in range(20, 105, 25):
            cv2.circle(base, (x, y), 3, (255, 255, 255), -1)
    matrix = np.float32([[1, 0, 8], [0, 1, 0]])
    shifted = cv2.warpAffine(base, matrix, (160, 120))
    return encode_jpeg(base), encode_jpeg(shifted)


def _scaled_frames(scale: float = 0.92):
    import cv2
    import numpy as np

    base = np.zeros((120, 160, 3), dtype=np.uint8)
    for x in range(20, 150, 30):
        for y in range(20, 105, 25):
            cv2.circle(base, (x, y), 3, (255, 255, 255), -1)
    matrix = cv2.getRotationMatrix2D((80, 60), 0, scale)
    scaled = cv2.warpAffine(base, matrix, (160, 120))
    return encode_jpeg(base), encode_jpeg(scaled)


def test_estimate_motion_detects_lateral_image_shift() -> None:
    previous, current = _shifted_frames()
    config = StabilizerConfig(mode="log", min_features=4, flow_threshold_px=1.0)

    estimate = estimate_motion(previous, current, config)

    assert estimate.tracked_features >= 4
    assert estimate.median_dx_px > 4.0
    assert _left_right_correction(estimate, config) > 0


def test_estimate_motion_detects_radial_image_contraction() -> None:
    previous, current = _scaled_frames(scale=0.9)
    config = StabilizerConfig(mode="log", min_features=4)

    estimate = estimate_motion(previous, current, config)

    assert estimate.tracked_features >= 4
    assert estimate.median_radial_px < -1.0


def test_stabilizer_ignores_contradictory_low_tof_when_height_is_safe() -> None:
    telemetry = DroneTelemetry(
        connected=True,
        flying=True,
        height_cm=80,
        raw={"tof": 31, "pitch": 0, "roll": 0},
    )
    config = StabilizerConfig(mode="log", min_height_cm=35, safety_min_tof_cm=60)
    estimate = MotionEstimate(
        median_dx_px=0.0,
        median_dy_px=0.0,
        median_radial_px=0.0,
        tracked_features=40,
        frame_width=160,
        frame_height=120,
    )

    assert _telemetry_guard(telemetry, config) is None
    assert _safety_guard_reasons(telemetry, estimate, config) == []


@pytest.mark.asyncio
async def test_stabilizer_log_mode_does_not_send_commands(tmp_path) -> None:
    adapter = SimAdapter()
    await adapter.connect()
    await adapter.takeoff()
    safety = SafetyController(adapter, AsyncEventBus())
    safety._last_command_at -= 10.0
    store = FrameStore(sample_fps=1000)
    previous, current = _shifted_frames()
    store.update_jpeg(previous, width=160, height=120)
    stabilizer = FlightStabilizer(
        safety,
        store,
        AsyncEventBus(),
        config=StabilizerConfig(mode="log", min_features=4, flow_threshold_px=1.0, safety_guard_enabled=False),
        log_dir=str(tmp_path),
        run_id="stab-log",
    )

    await stabilizer._tick()
    store.update_jpeg(current, width=160, height=120)
    await stabilizer._tick()

    assert not any(command[0] == "rc_control" for command in adapter.commands)
    assert stabilizer.status()["last_skip_reason"] == "log_only"


@pytest.mark.asyncio
async def test_stabilizer_assist_sends_tiny_correction_when_idle(tmp_path) -> None:
    adapter = SimAdapter()
    await adapter.connect()
    await adapter.takeoff()
    safety = SafetyController(adapter, AsyncEventBus())
    await safety.execute(DroneCommand(type=CommandType.HOVER, issued_by="test"))
    safety._last_command_at -= 10.0
    store = FrameStore(sample_fps=1000)
    previous, current = _shifted_frames()
    store.update_jpeg(previous, width=160, height=120)
    stabilizer = FlightStabilizer(
        safety,
        store,
        AsyncEventBus(),
        config=StabilizerConfig(
            mode="assist",
            min_features=4,
            flow_threshold_px=1.0,
            idle_after_s=0.0,
            max_left_right=6,
            duration_ms=50,
            safety_guard_enabled=False,
        ),
        log_dir=str(tmp_path),
        run_id="stab-assist",
    )

    await stabilizer._tick()
    store.update_jpeg(current, width=160, height=120)
    await stabilizer._tick()
    await asyncio.sleep(0)

    rc_commands = [command for command in adapter.commands if command[0] == "rc_control"]
    assert rc_commands
    assert 0 < rc_commands[-1][1][0] <= 6
    assert stabilizer.status()["last_correction"]["left_right"] == rc_commands[-1][1][0]


@pytest.mark.asyncio
async def test_stabilizer_safety_guard_lands_in_log_mode(tmp_path) -> None:
    adapter = SimAdapter()
    await adapter.connect()
    await adapter.takeoff()
    safety = SafetyController(adapter, AsyncEventBus())
    safety._last_command_at -= 10.0
    store = FrameStore(sample_fps=1000)
    previous, current = _shifted_frames()
    store.update_jpeg(previous, width=160, height=120)
    stabilizer = FlightStabilizer(
        safety,
        store,
        AsyncEventBus(),
        config=StabilizerConfig(
            mode="log",
            min_features=4,
            safety_flow_threshold_px=1.0,
            safety_land_after=1,
        ),
        log_dir=str(tmp_path),
        run_id="stab-guard",
    )

    await stabilizer._tick()
    store.update_jpeg(current, width=160, height=120)
    await stabilizer._tick()

    assert ("land", ()) in adapter.commands
    assert stabilizer.status()["last_skip_reason"].startswith("safety_guard:")


@pytest.mark.asyncio
async def test_stabilizer_safety_guard_ignores_flow_during_recent_command(tmp_path) -> None:
    adapter = SimAdapter()
    await adapter.connect()
    await adapter.takeoff()
    safety = SafetyController(adapter, AsyncEventBus())
    await safety.execute(DroneCommand(type=CommandType.HOVER, issued_by="test"))
    store = FrameStore(sample_fps=1000)
    previous, current = _shifted_frames()
    store.update_jpeg(previous, width=160, height=120)
    stabilizer = FlightStabilizer(
        safety,
        store,
        AsyncEventBus(),
        config=StabilizerConfig(
            mode="log",
            min_features=4,
            safety_flow_threshold_px=1.0,
            safety_land_after=1,
            idle_after_s=10.0,
        ),
        log_dir=str(tmp_path),
        run_id="stab-recent-command",
    )

    await stabilizer._tick()
    store.update_jpeg(current, width=160, height=120)
    await stabilizer._tick()

    assert ("land", ()) not in adapter.commands
    assert stabilizer.status()["last_skip_reason"] == "safety_guard_command_channel_not_idle"


@pytest.mark.asyncio
async def test_stabilizer_safety_guard_catches_forward_back_drift(tmp_path) -> None:
    adapter = SimAdapter()
    await adapter.connect()
    await adapter.takeoff()
    safety = SafetyController(adapter, AsyncEventBus())
    safety._last_command_at -= 10.0
    store = FrameStore(sample_fps=1000)
    previous, current = _scaled_frames(scale=0.9)
    store.update_jpeg(previous, width=160, height=120)
    stabilizer = FlightStabilizer(
        safety,
        store,
        AsyncEventBus(),
        config=StabilizerConfig(
            mode="log",
            min_features=4,
            safety_flow_threshold_px=50.0,
            safety_radial_threshold_px=1.0,
            safety_land_after=1,
        ),
        log_dir=str(tmp_path),
        run_id="stab-radial-guard",
    )

    await stabilizer._tick()
    store.update_jpeg(current, width=160, height=120)
    await stabilizer._tick()

    assert ("land", ()) in adapter.commands
    assert "image_radial_contracting" in stabilizer.status()["last_skip_reason"]
