from __future__ import annotations

from typing import Any

from breacheye.rafa.adapters import DetectionAdapter, DepthAdapter, NavigationAdapter
from breacheye.rafa.schemas import DepthOutput, DetectionOutput, FrameInput, NavigationOutput


class ModelUnavailable(RuntimeError):
    pass


class LazyMoondreamDetector(DetectionAdapter):
    name = "moondream"

    def __init__(self) -> None:
        try:
            import moondream  # noqa: F401
        except ImportError as exc:
            raise ModelUnavailable("moondream package is not installed") from exc
        raise ModelUnavailable("moondream weights are not configured")

    async def detect(self, frame: Any, meta: FrameInput) -> DetectionOutput:
        raise ModelUnavailable("moondream detector is unavailable")


class LazyDepthAnythingV2Estimator(DepthAdapter):
    name = "depth_anything_v2"

    def __init__(self) -> None:
        try:
            import depth_anything_v2  # noqa: F401
        except ImportError as exc:
            raise ModelUnavailable("Depth Anything V2 package is not installed") from exc
        raise ModelUnavailable("Depth Anything V2 weights are not configured")

    async def estimate(self, frame: Any, meta: FrameInput) -> DepthOutput:
        raise ModelUnavailable("Depth Anything V2 estimator is unavailable")


class LazyQwen3VLNavigator(NavigationAdapter):
    name = "qwen3_vl"

    def __init__(self) -> None:
        raise ModelUnavailable("Qwen3-VL runtime and weights are not configured")

    async def decide(
        self,
        frame: Any,
        meta: FrameInput,
        detections: DetectionOutput,
        depth: DepthOutput | None,
    ) -> NavigationOutput:
        raise ModelUnavailable("Qwen3-VL navigator is unavailable")
