from __future__ import annotations

from abc import ABC, abstractmethod
from time import monotonic, time
from typing import Any

from breacheye.rafa.schemas import (
    BBox2D,
    DepthOutput,
    Detection,
    DetectionOutput,
    FrameInput,
    NavigationDecision,
    NavigationOutput,
)


class DetectionAdapter(ABC):
    name: str

    @abstractmethod
    async def detect(self, frame: Any, meta: FrameInput) -> DetectionOutput:
        raise NotImplementedError


class DepthAdapter(ABC):
    name: str

    @abstractmethod
    async def estimate(self, frame: Any, meta: FrameInput) -> DepthOutput:
        raise NotImplementedError


class NavigationAdapter(ABC):
    name: str

    @abstractmethod
    async def decide(
        self,
        frame: Any,
        meta: FrameInput,
        detections: DetectionOutput,
        depth: DepthOutput | None,
    ) -> NavigationOutput:
        raise NotImplementedError


class StubDetector(DetectionAdapter):
    name = "stub-detector"

    async def detect(self, frame: Any, meta: FrameInput) -> DetectionOutput:
        started = monotonic()
        height, width = _frame_shape(frame)
        detection = Detection(
            id=f"det-{meta.frame_id:03d}-001",
            category="ROOM",
            label="Room/Open Area",
            description="Stub open-area detection for integration testing",
            confidence=0.65,
            bbox_2d=BBox2D(
                x1=max(0, width // 4),
                y1=max(0, height // 4),
                x2=max(1, (width * 3) // 4),
                y2=max(1, (height * 3) // 4),
            ),
            threat_level="INFO",
            detection_model=self.name,
        )
        return DetectionOutput(
            frame_id=meta.frame_id,
            timestamp=time(),
            detections=[detection],
            processing_ms=max(0, int((monotonic() - started) * 1000)),
        )


class StubDepthEstimator(DepthAdapter):
    name = "stub-depth"

    async def estimate(self, frame: Any, meta: FrameInput) -> DepthOutput:
        import numpy as np

        height, width = _frame_shape(frame)
        row = np.linspace(0.2, 0.9, height, dtype=np.float32).reshape(height, 1)
        depth = np.repeat(row, width, axis=1)
        return DepthOutput(
            frame_id=meta.frame_id,
            timestamp=time(),
            shape=(height, width),
            depth_bytes=depth.tobytes(),
        )


class SafeRuleNavigator(NavigationAdapter):
    name = "safe-rule-navigator"

    async def decide(
        self,
        frame: Any,
        meta: FrameInput,
        detections: DetectionOutput,
        depth: DepthOutput | None,
    ) -> NavigationOutput:
        close_obstacle = _has_close_center_obstacle(depth)
        if close_obstacle:
            decision = NavigationDecision(
                action="rotate_right",
                params={"degrees": 20},
                confidence=0.72,
                reasoning="Close obstacle in center depth band; rotating to search for a clear path",
                exploration_state="obstacle_avoidance",
            )
        else:
            decision = NavigationDecision(
                action="move_forward",
                params={"distance_cm": 30, "speed_cm_s": 20},
                confidence=0.7,
                reasoning="Stub depth indicates no close center obstacle",
                exploration_state="exploring",
            )
        return NavigationOutput(frame_id=meta.frame_id, timestamp=time(), decision=decision)


class HoverNavigator(NavigationAdapter):
    name = "hover-navigator"

    async def decide(
        self,
        frame: Any,
        meta: FrameInput,
        detections: DetectionOutput,
        depth: DepthOutput | None,
    ) -> NavigationOutput:
        return NavigationOutput(
            frame_id=meta.frame_id,
            timestamp=time(),
            decision=NavigationDecision(
                action="hover",
                params={"duration_ms": 500},
                confidence=1.0,
                reasoning="Safe fallback navigation",
                exploration_state="exploring",
            ),
        )


def _frame_shape(frame: Any) -> tuple[int, int]:
    shape = getattr(frame, "shape", None)
    if shape is None or len(shape) < 2:
        return (720, 960)
    return (int(shape[0]), int(shape[1]))


def _has_close_center_obstacle(depth: DepthOutput | None) -> bool:
    if depth is None:
        return True
    try:
        import numpy as np

        values = np.frombuffer(depth.depth_bytes, dtype=np.float32).reshape(depth.shape)
        height, width = values.shape
        band = values[height // 3 : (height * 2) // 3, width // 3 : (width * 2) // 3]
        finite = band[np.isfinite(band)]
        if not finite.size:
            return True
        return bool(float(np.nanpercentile(finite, 50)) < 0.15)
    except Exception:
        return True
