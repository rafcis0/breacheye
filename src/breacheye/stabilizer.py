from __future__ import annotations

import asyncio
import os
from dataclasses import asdict, dataclass
from time import time
from typing import Literal

from breacheye.bus import AsyncEventBus
from breacheye.models import CommandType, DroneCommand, DroneTelemetry, RCControlPayload
from breacheye.runlog import RunLogger
from breacheye.safety import SafetyController
from breacheye.video import FrameStore

StabilizerMode = Literal["off", "log", "assist"]


@dataclass(frozen=True)
class StabilizerConfig:
    mode: StabilizerMode = "off"
    interval_s: float = 0.5
    idle_after_s: float = 0.9
    flow_threshold_px: float = 1.5
    gain: float = 0.25
    max_left_right: int = 6
    duration_ms: int = 150
    min_features: int = 12
    max_attitude_deg: float = 25.0
    min_height_cm: int = 35
    max_tof_cm: int = 500
    resized_width: int = 160
    safety_guard_enabled: bool = True
    safety_flow_threshold_px: float = 6.0
    safety_radial_threshold_px: float = 2.0
    safety_min_tof_cm: int = 60
    safety_land_after: int = 2

    @classmethod
    def from_env(cls, mode: str | None = None) -> "StabilizerConfig":
        selected = (mode or os.environ.get("BREACHEYE_STABILIZER_MODE", "off")).strip().lower()
        if selected not in {"off", "log", "assist"}:
            selected = "off"
        return cls(
            mode=selected,  # type: ignore[arg-type]
            interval_s=_env_float("BREACHEYE_STABILIZER_INTERVAL_S", 0.5, minimum=0.1, maximum=5.0),
            idle_after_s=_env_float("BREACHEYE_STABILIZER_IDLE_AFTER_S", 0.9, minimum=0.0, maximum=10.0),
            flow_threshold_px=_env_float("BREACHEYE_STABILIZER_FLOW_THRESHOLD_PX", 1.5, minimum=0.1, maximum=25.0),
            gain=_env_float("BREACHEYE_STABILIZER_GAIN", 0.25, minimum=0.01, maximum=2.0),
            max_left_right=_env_int("BREACHEYE_STABILIZER_MAX_LEFT_RIGHT", 6, minimum=1, maximum=15),
            duration_ms=_env_int("BREACHEYE_STABILIZER_DURATION_MS", 150, minimum=50, maximum=500),
            min_features=_env_int("BREACHEYE_STABILIZER_MIN_FEATURES", 12, minimum=4, maximum=200),
            max_attitude_deg=_env_float("BREACHEYE_STABILIZER_MAX_ATTITUDE_DEG", 25.0, minimum=5.0, maximum=60.0),
            min_height_cm=_env_int("BREACHEYE_STABILIZER_MIN_HEIGHT_CM", 35, minimum=0, maximum=200),
            max_tof_cm=_env_int("BREACHEYE_STABILIZER_MAX_TOF_CM", 500, minimum=30, maximum=1000),
            resized_width=_env_int("BREACHEYE_STABILIZER_RESIZED_WIDTH", 160, minimum=80, maximum=640),
            safety_guard_enabled=_env_bool("BREACHEYE_STABILIZER_SAFETY_GUARD_ENABLED", True),
            safety_flow_threshold_px=_env_float(
                "BREACHEYE_STABILIZER_SAFETY_FLOW_THRESHOLD_PX",
                6.0,
                minimum=1.0,
                maximum=80.0,
            ),
            safety_radial_threshold_px=_env_float(
                "BREACHEYE_STABILIZER_SAFETY_RADIAL_THRESHOLD_PX",
                2.0,
                minimum=0.1,
                maximum=40.0,
            ),
            safety_min_tof_cm=_env_int("BREACHEYE_STABILIZER_SAFETY_MIN_TOF_CM", 60, minimum=0, maximum=300),
            safety_land_after=_env_int("BREACHEYE_STABILIZER_SAFETY_LAND_AFTER", 2, minimum=1, maximum=10),
        )


@dataclass(frozen=True)
class MotionEstimate:
    median_dx_px: float
    median_dy_px: float
    median_radial_px: float
    tracked_features: int
    frame_width: int
    frame_height: int


class FlightStabilizer:
    """Optional optical-flow drift logger/corrector.

    This is deliberately conservative. It only estimates lateral image drift and
    only sends tiny left/right RC pulses in assist mode after the regular safety
    command channel has been idle. It never corrects while grounded, tilted,
    too low, or while another command is active.
    """

    def __init__(
        self,
        safety: SafetyController,
        frame_store: FrameStore,
        bus: AsyncEventBus,
        *,
        config: StabilizerConfig | None = None,
        log_dir: str | None = "logs",
        run_id: str | None = None,
    ) -> None:
        self.safety = safety
        self.frame_store = frame_store
        self.bus = bus
        self.config = config or StabilizerConfig()
        self.logger = RunLogger("stabilizer", log_dir=log_dir, run_id=run_id)
        self._task: asyncio.Task | None = None
        self._prev_jpeg: bytes | None = None
        self._last_estimate: dict | None = None
        self._last_correction: dict | None = None
        self._last_skip_reason: str | None = None
        self._safety_guard_streak: int = 0

    async def start(self) -> None:
        self.logger.event("stabilizer_config", config=asdict(self.config))
        if self.config.mode == "off":
            return
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="flight-stabilizer")
            self.logger.event("stabilizer_start", mode=self.config.mode)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self.logger.event("stabilizer_stop")

    def status(self) -> dict:
        return {
            "mode": self.config.mode,
            "running": self._task is not None and not self._task.done(),
            "config": asdict(self.config),
            "last_estimate": self._last_estimate,
            "last_correction": self._last_correction,
            "last_skip_reason": self._last_skip_reason,
        }

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.config.interval_s)
            await self._tick()

    async def _tick(self) -> None:
        telemetry = await self.safety.telemetry()
        guard = _telemetry_guard(telemetry, self.config)
        jpeg = self.frame_store.latest_full_jpeg()
        event_base = {"telemetry": telemetry.model_dump(mode="json"), "guard": guard}

        if guard is not None:
            self._last_skip_reason = guard
            self._prev_jpeg = jpeg
            self._log("stabilizer_skipped", reason=guard, **event_base)
            return
        if jpeg is None:
            self._last_skip_reason = "no_full_frame"
            self._log("stabilizer_skipped", reason="no_full_frame", **event_base)
            return
        if self._prev_jpeg is None:
            self._prev_jpeg = jpeg
            self._last_skip_reason = "need_previous_frame"
            self._log("stabilizer_skipped", reason="need_previous_frame", **event_base)
            return

        try:
            estimate = estimate_motion(self._prev_jpeg, jpeg, self.config)
        except Exception as exc:
            self._prev_jpeg = jpeg
            self._last_skip_reason = f"motion_estimate_failed: {exc}"
            self._log("stabilizer_estimate_failed", error=str(exc), **event_base)
            return
        self._prev_jpeg = jpeg

        estimate_payload = asdict(estimate)
        self._last_estimate = {**estimate_payload, "timestamp": time()}
        correction = _left_right_correction(estimate, self.config)
        command_age_s = self.safety.last_command_age_s()
        self._log(
            "stabilizer_motion_estimate",
            **event_base,
            estimate=estimate_payload,
            proposed_left_right=correction,
            command_age_s=command_age_s,
        )

        if await self._run_safety_guard(telemetry, estimate, command_age_s):
            return

        if correction == 0:
            self._last_skip_reason = "below_flow_threshold"
            self._log("stabilizer_correction_skipped", reason="below_flow_threshold", estimate=estimate_payload)
            return
        if self.config.mode == "log":
            self._last_skip_reason = "log_only"
            self._log(
                "stabilizer_correction_skipped",
                reason="log_only",
                proposed_left_right=correction,
                estimate=estimate_payload,
            )
            return
        if command_age_s < self.config.idle_after_s:
            self._last_skip_reason = "command_channel_not_idle"
            self._log(
                "stabilizer_correction_skipped",
                reason="command_channel_not_idle",
                proposed_left_right=correction,
                command_age_s=command_age_s,
                idle_after_s=self.config.idle_after_s,
            )
            return

        command = DroneCommand(
            type=CommandType.RC_CONTROL,
            issued_by="stabilizer",
            ttl_ms=self.config.duration_ms + 200,
            payload=RCControlPayload(
                left_right=correction,
                forward_back=0,
                up_down=0,
                yaw=0,
                duration_ms=self.config.duration_ms,
            ),
        )
        self._log(
            "stabilizer_correction_commanded",
            command=command.model_dump(mode="json"),
            estimate=estimate_payload,
        )
        result = await self.safety.execute(command)
        self._last_correction = {
            "timestamp": time(),
            "left_right": correction,
            "result": result.model_dump(mode="json"),
            "estimate": estimate_payload,
        }
        self._log("stabilizer_correction_result", correction=self._last_correction)

    async def _run_safety_guard(
        self,
        telemetry: DroneTelemetry,
        estimate: MotionEstimate,
        command_age_s: float,
    ) -> bool:
        reasons = _safety_guard_reasons(telemetry, estimate, self.config)
        if not reasons:
            self._safety_guard_streak = 0
            return False

        self._safety_guard_streak += 1
        command_type = CommandType.LAND if self._safety_guard_streak >= self.config.safety_land_after else CommandType.HOVER
        command = DroneCommand(type=command_type, issued_by="stabilizer_safety_guard")
        self._log(
            "stabilizer_safety_guard",
            command=command.model_dump(mode="json"),
            command_age_s=command_age_s,
            reasons=reasons,
            safety_guard_streak=self._safety_guard_streak,
            safety_land_after=self.config.safety_land_after,
            estimate=asdict(estimate),
            telemetry=telemetry.model_dump(mode="json"),
        )
        result = await self.safety.execute(command)
        self._last_correction = {
            "timestamp": time(),
            "left_right": 0,
            "result": result.model_dump(mode="json"),
            "estimate": asdict(estimate),
            "safety_guard": True,
            "reasons": reasons,
        }
        self._log("stabilizer_safety_guard_result", correction=self._last_correction)
        self._last_skip_reason = "safety_guard:" + ",".join(reasons)
        return True

    def _log(self, event: str, **fields) -> None:
        self.logger.event(event, **fields)
        try:
            asyncio.create_task(self.bus.publish("drone.stabilizer", {"event": event, **fields}))
        except RuntimeError:
            pass


def estimate_motion(previous_jpeg: bytes, current_jpeg: bytes, config: StabilizerConfig) -> MotionEstimate:
    import cv2
    import numpy as np

    previous = _decode_gray(previous_jpeg, config.resized_width)
    current = _decode_gray(current_jpeg, config.resized_width)
    features = cv2.goodFeaturesToTrack(
        previous,
        maxCorners=120,
        qualityLevel=0.01,
        minDistance=7,
        blockSize=7,
    )
    if features is None or len(features) < config.min_features:
        count = 0 if features is None else len(features)
        raise ValueError(f"too_few_features:{count}")
    next_points, status, _err = cv2.calcOpticalFlowPyrLK(previous, current, features, None)
    if next_points is None or status is None:
        raise ValueError("optical_flow_failed")
    valid = status.reshape(-1) == 1
    if int(valid.sum()) < config.min_features:
        raise ValueError(f"too_few_tracked_features:{int(valid.sum())}")
    previous_points = features[valid].reshape(-1, 2)
    deltas = (next_points[valid] - features[valid]).reshape(-1, 2)
    median_dx = float(np.median(deltas[:, 0]))
    median_dy = float(np.median(deltas[:, 1]))
    center = np.array([current.shape[1] / 2.0, current.shape[0] / 2.0], dtype=np.float32)
    radial = previous_points - center
    norms = np.linalg.norm(radial, axis=1)
    usable = norms > 1e-6
    if np.any(usable):
        radial_unit = radial[usable] / norms[usable, None]
        radial_motion = np.sum(deltas[usable] * radial_unit, axis=1)
        median_radial = float(np.median(radial_motion))
    else:
        median_radial = 0.0
    return MotionEstimate(
        median_dx_px=median_dx,
        median_dy_px=median_dy,
        median_radial_px=median_radial,
        tracked_features=int(valid.sum()),
        frame_width=int(current.shape[1]),
        frame_height=int(current.shape[0]),
    )


def _decode_gray(jpeg: bytes, resized_width: int):
    import cv2
    import numpy as np

    data = np.frombuffer(jpeg, dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError("invalid_jpeg")
    if image.shape[1] > resized_width:
        scale = resized_width / image.shape[1]
        image = cv2.resize(image, (resized_width, max(1, int(image.shape[0] * scale))))
    return image


def _left_right_correction(estimate: MotionEstimate, config: StabilizerConfig) -> int:
    if abs(estimate.median_dx_px) < config.flow_threshold_px:
        return 0
    # Positive image dx usually means the camera drifted left, so nudge right.
    raw = int(round(estimate.median_dx_px * config.gain))
    if raw == 0:
        raw = 1 if estimate.median_dx_px > 0 else -1
    return max(-config.max_left_right, min(config.max_left_right, raw))


def _safety_guard_reasons(
    telemetry: DroneTelemetry,
    estimate: MotionEstimate,
    config: StabilizerConfig,
) -> list[str]:
    if not config.safety_guard_enabled:
        return []
    reasons: list[str] = []
    if abs(estimate.median_dx_px) >= config.safety_flow_threshold_px:
        reasons.append(f"image_dx={estimate.median_dx_px:.1f}px")
    if abs(estimate.median_dy_px) >= config.safety_flow_threshold_px:
        reasons.append(f"image_dy={estimate.median_dy_px:.1f}px")
    if abs(estimate.median_radial_px) >= config.safety_radial_threshold_px:
        direction = "expanding" if estimate.median_radial_px > 0 else "contracting"
        reasons.append(f"image_radial_{direction}={estimate.median_radial_px:.1f}px")
    raw = telemetry.raw or {}
    tof = _float_or_none(raw.get("tof"))
    if tof is not None and tof < config.safety_min_tof_cm:
        reasons.append(f"tof={tof:g}cm<{config.safety_min_tof_cm}cm")
    return reasons


def _telemetry_guard(telemetry: DroneTelemetry, config: StabilizerConfig) -> str | None:
    if telemetry.connected is not True:
        return "not_connected"
    if telemetry.flying is not True:
        return "not_flying"
    if telemetry.height_cm is not None and telemetry.height_cm < config.min_height_cm:
        return f"height_too_low:{telemetry.height_cm}"
    raw = telemetry.raw or {}
    pitch = _float_or_none(raw.get("pitch"))
    roll = _float_or_none(raw.get("roll"))
    tof = _float_or_none(raw.get("tof"))
    if pitch is not None and abs(pitch) > config.max_attitude_deg:
        return f"pitch_guard:{pitch:g}"
    if roll is not None and abs(roll) > config.max_attitude_deg:
        return f"roll_guard:{roll:g}"
    if tof is not None and tof <= config.min_height_cm:
        return f"tof_too_low:{tof:g}"
    if tof is not None and tof > config.max_tof_cm:
        return f"tof_out_of_range:{tof:g}"
    return None


def _float_or_none(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
