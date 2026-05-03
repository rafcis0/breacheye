from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import monotonic, time

from pydantic import ValidationError

from breacheye.runlog import RunLogger, summarize_payload
from breacheye.rafa.adapters import (
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
    SmolVLMNavigator,
)
from breacheye.rafa.receiver import ZmqFrameReceiver
from breacheye.rafa.schemas import (
    DepthOutput,
    DetectionOutput,
    HealthOutput,
    MemoryStatus,
    NavigationAction,
    ModelStatus,
    NavigationOutput,
    Throughput,
)
from breacheye.rafa.spatial_context import build_spatial_context, summarize_spatial_context


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
    log_dir: str | None = "logs"
    run_id: str | None = None
    errors: list[str] = field(default_factory=list)


class RafaPipeline:
    def __init__(self, config: RafaPipelineConfig | None = None) -> None:
        self.config = config or RafaPipelineConfig()
        self._context = None
        self._receiver: ZmqFrameReceiver | None = None
        self._sockets: dict[str, object] = {}
        self._running = False
        self._frames = {"detection": 0, "depth": 0, "decision": 0}
        self._recent_actions: list[NavigationAction] = []
        self._started_at = monotonic()
        self._last_health_at = 0.0
        self.errors = list(self.config.errors)
        self.logger = RunLogger("rafa", log_dir=self.config.log_dir, run_id=self.config.run_id)
        self.detector = StubDetector()
        self.depth_estimator = StubDepthEstimator()
        self.navigator = SafeRuleNavigator()
        self.model_status = {
            "moondream": ModelStatus(status="stub", active=self.detector.name),
            "depth_anything_v2": ModelStatus(status="stub", active=self.depth_estimator.name),
            "qwen3_vl": ModelStatus(status="stub", active=self.navigator.name),
        }

    def configure_adapters(self) -> None:
        self.logger.event("configure_adapters_start", mode=self.config.mode)
        if self.config.mode == "stub":
            self.logger.event("configure_adapters_done", models={key: value.model_dump() for key, value in self.model_status.items()})
            return
        if self.config.mode not in {"models", "detector-only"}:
            raise ValueError(f"unsupported Rafa mode {self.config.mode!r}")

        try:
            self.detector = LazyMoondreamDetector()
            self.model_status["moondream"] = ModelStatus(status="ready", active=self.detector.name)
        except ModelUnavailable as exc:
            self.errors.append(str(exc))
            self.logger.event("model_fallback", model="moondream", error=str(exc), fallback="stub-detector")
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
            self.logger.event("configure_adapters_done", models={key: value.model_dump() for key, value in self.model_status.items()})
            return

        try:
            self.depth_estimator = LazyDepthAnythingV2Estimator()
            self.model_status["depth_anything_v2"] = ModelStatus(status="ready", active=self.depth_estimator.name)
        except ModelUnavailable as exc:
            self.errors.append(str(exc))
            self.logger.event("model_fallback", model="depth_anything_v2", error=str(exc), fallback="stub-depth")
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
            try:
                self.navigator = SmolVLMNavigator()
                self.model_status["qwen3_vl"] = ModelStatus(
                    status="fallback",
                    active=self.navigator.name,
                    error=f"{exc}; using SmolVLM fallback",
                )
                self.logger.event("model_fallback", model="qwen3_vl", error=str(exc), fallback="smolvlm2-500m")
            except ModelUnavailable as fallback_exc:
                self.logger.event(
                    "model_fallback",
                    model="qwen3_vl",
                    error=f"{exc}; {fallback_exc}",
                    fallback="safe-rule-navigator",
                )
                self.navigator = SafeRuleNavigator()
                self.model_status["qwen3_vl"] = ModelStatus(
                    status="fallback",
                    active=self.navigator.name,
                    error=str(exc),
                )
        self.logger.event("configure_adapters_done", models={key: value.model_dump() for key, value in self.model_status.items()})

    async def start(self) -> None:
        import zmq
        import zmq.asyncio

        self.configure_adapters()
        self.logger.event(
            "pipeline_start",
            mode=self.config.mode,
            frame_port=self.config.frame_port,
            detection_port=self.config.detection_port,
            depth_port=self.config.depth_port,
            navigation_port=self.config.navigation_port,
            health_port=self.config.health_port,
        )
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
        self.logger.event("pipeline_stop")
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
        frame_started_at = monotonic()
        timings: dict[str, float] = {}
        try:
            frame_meta = await self._receiver.recv(timeout_s=self.config.recv_timeout_s)
        except asyncio.TimeoutError:
            self.logger.event("frame_recv_timeout", timeout_s=self.config.recv_timeout_s)
            return False
        frame_path = self.logger.save_bytes("frames", f"frame-{frame_meta.frame_id:08d}.jpg", frame_meta.jpeg_bytes)
        self.logger.event(
            "frame_received",
            frame_id=frame_meta.frame_id,
            jpeg_bytes=len(frame_meta.jpeg_bytes),
            width=frame_meta.width,
            height=frame_meta.height,
            image_path=frame_path,
        )
        try:
            stage_started_at = monotonic()
            frame = decode_jpeg_bgr(frame_meta.jpeg_bytes)
            timings["decode_ms"] = _elapsed_ms(stage_started_at)
        except Exception as exc:
            self.errors.append(f"frame {frame_meta.frame_id}: {exc}")
            self.logger.event("frame_decode_failed", frame_id=frame_meta.frame_id, error=str(exc))
            await self.publish_health()
            return False

        stage_started_at = monotonic()
        detection = await self._safe_detect(frame, frame_meta)
        timings["detection_ms"] = _elapsed_ms(stage_started_at)
        stage_started_at = monotonic()
        depth = await self._safe_depth(frame, frame_meta)
        timings["depth_ms"] = _elapsed_ms(stage_started_at)
        if depth is not None:
            self._log_depth_artifact(depth)
        stage_started_at = monotonic()
        navigation = await self._safe_navigation(frame, frame_meta, detection, depth)
        timings["navigation_ms"] = _elapsed_ms(stage_started_at)
        stage_started_at = monotonic()
        await self._publish("detections", detection)
        if depth is not None:
            await self._publish("depth", depth)
        await self._publish("navigation", navigation)
        timings["publish_ms"] = _elapsed_ms(stage_started_at)
        self.logger.event(
            "frame_pipeline_summary",
            frame_id=frame_meta.frame_id,
            total_ms=_elapsed_ms(frame_started_at),
            depth_available=depth is not None,
            action=navigation.decision.action,
            confidence=navigation.decision.confidence,
            **timings,
        )
        return True

    async def publish_health(self) -> None:
        health = self.health()
        await self._publish("health", health)
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
            self.logger.event("detection_fallback", frame_id=frame_meta.frame_id, error=str(exc))
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
            self.logger.event("depth_fallback", frame_id=frame_meta.frame_id, error=str(exc))
            try:
                fallback = await StubDepthEstimator().estimate(frame, frame_meta)
                self._frames["depth"] += 1
                return fallback
            except Exception:
                return None

    async def _safe_navigation(self, frame, frame_meta, detection, depth) -> NavigationOutput:
        context = build_spatial_context(
            meta=frame_meta,
            detections=detection,
            depth=depth,
            recent_actions=self._recent_actions,
        )
        self.logger.event(
            "navigation_context_built",
            frame_id=frame_meta.frame_id,
            summary=summarize_spatial_context(context),
            context=context.model_dump(mode="json"),
        )
        try:
            output = await self.navigator.decide(frame, frame_meta, detection, depth)
            validated = NavigationOutput.model_validate(output.model_dump())
            self._frames["decision"] += 1
            self._recent_actions.append(validated.decision.action)
            self.logger.event(
                "navigation_decision_built",
                frame_id=frame_meta.frame_id,
                action=validated.decision.action,
                confidence=validated.decision.confidence,
                reasoning=validated.decision.reasoning,
                params=validated.decision.params,
                exploration_state=validated.decision.exploration_state,
            )
            return validated
        except (ValidationError, Exception) as exc:
            self.errors.append(f"navigation fallback on frame {frame_meta.frame_id}: {exc}")
            self.logger.event("navigation_fallback", frame_id=frame_meta.frame_id, error=str(exc))
            fallback = await SafeRuleNavigator().decide(frame, frame_meta, detection, depth)
            self._frames["decision"] += 1
            self._recent_actions.append(fallback.decision.action)
            self.logger.event(
                "navigation_decision_built",
                frame_id=frame_meta.frame_id,
                action=fallback.decision.action,
                confidence=fallback.decision.confidence,
                reasoning=fallback.decision.reasoning,
                params=fallback.decision.params,
                exploration_state=fallback.decision.exploration_state,
                fallback=True,
            )
            return fallback

    async def _maybe_publish_health(self) -> None:
        if monotonic() - self._last_health_at >= self.config.health_interval_s:
            await self.publish_health()

    async def _publish(self, channel: str, payload) -> None:
        socket = self._sockets.get(channel)
        if socket is None:
            raise RuntimeError(f"publisher {channel!r} is not started")
        self.logger.event("publish", channel=channel, summary=summarize_payload(payload))
        if channel in {"detections", "navigation", "health"}:
            await socket.send(encode_json(payload))
        else:
            await socket.send(encode_msgpack(payload))

    def _log_depth_artifact(self, depth: DepthOutput) -> None:
        try:
            import io

            import cv2
            import numpy as np

            values = np.frombuffer(depth.depth_bytes, dtype=np.float32).reshape(depth.shape)
            raw_buffer = io.BytesIO()
            np.save(raw_buffer, values.astype(np.float32, copy=False))
            raw_path = self.logger.save_bytes("depth_raw", f"frame-{depth.frame_id:08d}.npy", raw_buffer.getvalue())
            self.logger.event(
                "depth_array_saved",
                frame_id=depth.frame_id,
                array_path=raw_path,
                width=int(depth.shape[1]),
                height=int(depth.shape[0]),
                dtype="float32",
            )
            finite = np.isfinite(values)
            if finite.any():
                near = float(np.nanpercentile(values[finite], 2))
                far = float(np.nanpercentile(values[finite], 98))
                denom = max(far - near, 1e-6)
                visual = np.clip((values - near) / denom, 0.0, 1.0)
            else:
                visual = np.zeros(depth.shape, dtype=np.float32)
            grayscale = (visual * 255).astype(np.uint8)
            color = cv2.applyColorMap(grayscale, cv2.COLORMAP_TURBO)
            ok, encoded = cv2.imencode(".png", color)
            if not ok:
                raise ValueError("cv2.imencode returned false")
            path = self.logger.save_bytes("depth", f"frame-{depth.frame_id:08d}.png", encoded.tobytes())
            self.logger.event(
                "depth_image_saved",
                frame_id=depth.frame_id,
                image_path=path,
                width=int(depth.shape[1]),
                height=int(depth.shape[0]),
            )
        except Exception as exc:
            self.logger.event("depth_image_save_failed", frame_id=depth.frame_id, error=str(exc))


def _elapsed_ms(started_at: float) -> int:
    return int((monotonic() - started_at) * 1000)
