from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import monotonic, time

from pydantic import ValidationError

from breacheye.rafa.adapters import (
    HoverNavigator,
    SafeRuleNavigator,
    StubDepthEstimator,
    StubDetector,
)
from breacheye.rafa.codec import encode_json, encode_msgpack
from breacheye.rafa.jpeg import decode_jpeg_bgr
from breacheye.rafa.models import (
    LazyDepthAnythingV2Estimator,
    LazyMoondreamDetector,
    LazyQwen3VLNavigator,
    ModelUnavailable,
)
from breacheye.rafa.receiver import ZmqFrameReceiver
from breacheye.rafa.schemas import (
    DepthOutput,
    DetectionOutput,
    HealthOutput,
    MemoryStatus,
    ModelStatus,
    NavigationOutput,
    Throughput,
)


@dataclass(frozen=True)
class RafaPipelineConfig:
    mode: str = "stub"
    host: str = "127.0.0.1"
    frame_port: int = 5555
    detection_port: int = 5556
    depth_port: int = 5557
    navigation_port: int = 5558
    health_port: int = 5559
    health_interval_s: float = 1.0
    recv_timeout_s: float = 0.5
    bind_publishers: bool = True
    errors: list[str] = field(default_factory=list)


class RafaPipeline:
    def __init__(self, config: RafaPipelineConfig | None = None) -> None:
        self.config = config or RafaPipelineConfig()
        self._context = None
        self._receiver: ZmqFrameReceiver | None = None
        self._sockets: dict[str, object] = {}
        self._running = False
        self._frames = {"detection": 0, "depth": 0, "decision": 0}
        self._started_at = monotonic()
        self._last_health_at = 0.0
        self.errors = list(self.config.errors)
        self.detector = StubDetector()
        self.depth_estimator = StubDepthEstimator()
        self.navigator = SafeRuleNavigator()
        self.model_status = {
            "moondream": ModelStatus(status="stub", active=self.detector.name),
            "depth_anything_v2": ModelStatus(status="stub", active=self.depth_estimator.name),
            "qwen3_vl": ModelStatus(status="stub", active=self.navigator.name),
        }

    def configure_adapters(self) -> None:
        if self.config.mode == "stub":
            return
        if self.config.mode not in {"models", "detector-only"}:
            raise ValueError(f"unsupported Rafa mode {self.config.mode!r}")

        try:
            self.detector = LazyMoondreamDetector()
            self.model_status["moondream"] = ModelStatus(status="ready", active=self.detector.name)
        except ModelUnavailable as exc:
            self.errors.append(str(exc))
            self.detector = StubDetector()
            self.model_status["moondream"] = ModelStatus(
                status="fallback",
                active=self.detector.name,
                error=str(exc),
            )

        if self.config.mode == "detector-only":
            self.depth_estimator = StubDepthEstimator()
            self.navigator = SafeRuleNavigator()
            self.model_status["depth_anything_v2"] = ModelStatus(status="stub", active=self.depth_estimator.name)
            self.model_status["qwen3_vl"] = ModelStatus(status="stub", active=self.navigator.name)
            return

        try:
            self.depth_estimator = LazyDepthAnythingV2Estimator()
            self.model_status["depth_anything_v2"] = ModelStatus(status="ready", active=self.depth_estimator.name)
        except ModelUnavailable as exc:
            self.errors.append(str(exc))
            self.depth_estimator = StubDepthEstimator()
            self.model_status["depth_anything_v2"] = ModelStatus(
                status="fallback",
                active=self.depth_estimator.name,
                error=str(exc),
            )

        try:
            self.navigator = LazyQwen3VLNavigator()
            self.model_status["qwen3_vl"] = ModelStatus(status="ready", active=self.navigator.name)
        except ModelUnavailable as exc:
            self.errors.append(str(exc))
            self.navigator = SafeRuleNavigator()
            self.model_status["qwen3_vl"] = ModelStatus(
                status="fallback",
                active=self.navigator.name,
                error=str(exc),
            )

    async def start(self) -> None:
        import zmq
        import zmq.asyncio

        self.configure_adapters()
        self._context = zmq.asyncio.Context.instance()
        self._receiver = ZmqFrameReceiver(f"tcp://{self.config.host}:{self.config.frame_port}", self._context)
        self._receiver.start()
        for name, port in {
            "detections": self.config.detection_port,
            "depth": self.config.depth_port,
            "navigation": self.config.navigation_port,
            "health": self.config.health_port,
        }.items():
            socket = self._context.socket(zmq.PUB)
            endpoint = f"tcp://{self.config.host}:{port}"
            if self.config.bind_publishers:
                socket.bind(endpoint)
            else:
                socket.connect(endpoint)
            self._sockets[name] = socket
        self._running = True
        await asyncio.sleep(0.05)
        await self.publish_health()

    async def stop(self) -> None:
        self._running = False
        if self._receiver is not None:
            self._receiver.close()
        for socket in self._sockets.values():
            socket.close(linger=0)
        self._sockets.clear()

    async def run_forever(self) -> None:
        await self.start()
        try:
            while self._running:
                await self.run_once()
        finally:
            await self.stop()

    async def run_once(self) -> bool:
        if self._receiver is None:
            raise RuntimeError("pipeline is not started")
        await self._maybe_publish_health()
        try:
            frame_meta = await self._receiver.recv(timeout_s=self.config.recv_timeout_s)
        except asyncio.TimeoutError:
            return False
        try:
            frame = decode_jpeg_bgr(frame_meta.jpeg_bytes)
        except Exception as exc:
            self.errors.append(f"frame {frame_meta.frame_id}: {exc}")
            await self.publish_health()
            return False

        detection = await self._safe_detect(frame, frame_meta)
        depth = await self._safe_depth(frame, frame_meta)
        navigation = await self._safe_navigation(frame, frame_meta, detection, depth)
        await self._publish("detections", detection)
        if depth is not None:
            await self._publish("depth", depth)
        await self._publish("navigation", navigation)
        return True

    async def publish_health(self) -> None:
        await self._publish("health", self.health())
        self._last_health_at = monotonic()

    def health(self) -> HealthOutput:
        status = "ready" if not self.errors else "degraded"
        elapsed = max(0.001, monotonic() - self._started_at)
        return HealthOutput(
            pipeline_status=status,
            models_loaded=self.model_status,
            throughput=Throughput(
                detection_fps=self._frames["detection"] / elapsed,
                depth_fps=self._frames["depth"] / elapsed,
                decision_fps=self._frames["decision"] / elapsed,
            ),
            memory=MemoryStatus(),
            errors=self.errors[-10:],
            timestamp=time(),
        )

    async def _safe_detect(self, frame, frame_meta) -> DetectionOutput:
        try:
            output = await self.detector.detect(frame, frame_meta)
            validated = DetectionOutput.model_validate(output.model_dump())
            self._frames["detection"] += 1
            return validated
        except Exception as exc:
            self.errors.append(f"detection fallback on frame {frame_meta.frame_id}: {exc}")
            fallback = await StubDetector().detect(frame, frame_meta)
            self._frames["detection"] += 1
            return fallback

    async def _safe_depth(self, frame, frame_meta):
        try:
            output = await self.depth_estimator.estimate(frame, frame_meta)
            validated = DepthOutput.model_validate(output.model_dump())
            self._frames["depth"] += 1
            return validated
        except Exception as exc:
            self.errors.append(f"depth unavailable on frame {frame_meta.frame_id}: {exc}")
            try:
                fallback = await StubDepthEstimator().estimate(frame, frame_meta)
                self._frames["depth"] += 1
                return fallback
            except Exception:
                return None

    async def _safe_navigation(self, frame, frame_meta, detection, depth) -> NavigationOutput:
        try:
            output = await self.navigator.decide(frame, frame_meta, detection, depth)
            validated = NavigationOutput.model_validate(output.model_dump())
            self._frames["decision"] += 1
            return validated
        except (ValidationError, Exception) as exc:
            self.errors.append(f"navigation fallback on frame {frame_meta.frame_id}: {exc}")
            fallback = await HoverNavigator().decide(frame, frame_meta, detection, depth)
            self._frames["decision"] += 1
            return fallback

    async def _maybe_publish_health(self) -> None:
        if monotonic() - self._last_health_at >= self.config.health_interval_s:
            await self.publish_health()

    async def _publish(self, channel: str, payload) -> None:
        socket = self._sockets.get(channel)
        if socket is None:
            raise RuntimeError(f"publisher {channel!r} is not started")
        if channel in {"detections", "navigation", "health"}:
            await socket.send(encode_json(payload))
        else:
            await socket.send(encode_msgpack(payload))
