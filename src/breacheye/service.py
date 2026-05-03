from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from breacheye.adapters.base import DroneAdapter
from breacheye.adapters.sim import SimAdapter
from breacheye.adapters.tello import TelloAdapter
from breacheye.bus import AsyncEventBus
from breacheye.models import CommandResult, CommandStatus, CommandType, DroneCommand
from breacheye.operator import OperatorCommand, OperatorHandler
from breacheye.safety import SafetyController
from breacheye.state_machine import FlightStateMachine
from breacheye.video import FrameStore, TelloVideoPump

log = logging.getLogger(__name__)

_ZMQ_DETECTIONS_PORT = 5556


class HarnessRuntime:
    """Owns the process-local drone resources exposed by the HTTP/WebSocket API."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.bus = AsyncEventBus()
        self.frame_store = FrameStore(sample_fps=1.0)
        self.adapter = make_adapter(mode)
        self.safety = SafetyController(self.adapter, self.bus)
        self.fsm = FlightStateMachine(self.adapter, self.bus)
        self.video_pump: TelloVideoPump | None = None
        self._zmq_task: asyncio.Task | None = None
        self._zmq_socket = None
        self._zmq_ctx = None

    async def start(self) -> None:
        await self.adapter.connect()
        await self.safety.start()
        if self.mode == "tello":
            self.video_pump = TelloVideoPump(self.adapter, self.frame_store, self.bus)
            await self.video_pump.start()
        self._start_zmq_bridge()

    def _start_zmq_bridge(self) -> None:
        try:
            import zmq
            import zmq.asyncio as azmq

            self._zmq_ctx = azmq.Context()
            self._zmq_socket = self._zmq_ctx.socket(zmq.SUB)
            self._zmq_socket.connect(f"tcp://localhost:{_ZMQ_DETECTIONS_PORT}")
            self._zmq_socket.setsockopt(zmq.SUBSCRIBE, b"")
            self._zmq_task = asyncio.create_task(
                self._zmq_reader(), name="zmq-detections-bridge"
            )
            log.info("ZMQ detections bridge started on port %d", _ZMQ_DETECTIONS_PORT)
        except ImportError:
            log.warning("pyzmq not installed — detection overlay bridge disabled")
        except Exception as exc:
            log.warning("ZMQ bridge init failed (%s) — detection overlay disabled", exc)
            self._cleanup_zmq()

    async def _zmq_reader(self) -> None:
        assert self._zmq_socket is not None
        backoff = 1.0
        max_backoff = 30.0
        while True:
            try:
                while True:
                    raw = await self._zmq_socket.recv()
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError as exc:
                        log.debug("ZMQ: bad JSON from detections channel: %s", exc)
                        continue
                    await self.bus.publish("drone.detections", payload)
                    backoff = 1.0
            except asyncio.CancelledError:
                return
            except Exception as exc:
                log.warning("ZMQ reader failed: %s — retrying in %.0fs", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    def _cleanup_zmq(self) -> None:
        if self._zmq_socket is not None:
            try:
                self._zmq_socket.close()
            except Exception:
                pass
            self._zmq_socket = None
        if self._zmq_ctx is not None:
            try:
                self._zmq_ctx.term()
            except Exception:
                pass
            self._zmq_ctx = None

    async def stop(self) -> None:
        try:
            telemetry = await self.safety.telemetry()
            if telemetry.flying:
                log.warning("runtime shutdown while flying; attempting land")
                await self.safety.execute(DroneCommand(type=CommandType.LAND, issued_by="runtime_shutdown"))
        except Exception as exc:
            log.warning("shutdown landing attempt failed: %s", exc)
        if self._zmq_task is not None:
            self._zmq_task.cancel()
            try:
                await self._zmq_task
            except asyncio.CancelledError:
                pass
            self._zmq_task = None
        self._cleanup_zmq()
        if self.video_pump is not None:
            await self.video_pump.stop()
        await self.safety.stop()
        await self.adapter.close()


def make_adapter(mode: str) -> DroneAdapter:
    if mode in {"sim", "dry_run"}:
        return SimAdapter()
    if mode == "tello":
        return TelloAdapter()
    raise ValueError(f"unsupported mode {mode!r}")


def create_app(mode: str = "sim") -> FastAPI:
    runtime = HarnessRuntime(mode)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await runtime.start()
        app.state.runtime = runtime
        try:
            yield
        finally:
            await runtime.stop()

    app = FastAPI(
        title="BreachEye Tello Harness",
        version="0.1.0",
        description=(
            "Structured safety boundary for Tello control. Raw SDK commands are "
            "intentionally not exposed to callers or future LLM agents."
        ),
        lifespan=lifespan,
    )

    # Hackathon: wide-open CORS for dev convenience. Lock down for production.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        telemetry = await runtime.safety.telemetry()
        return {
            "mode": runtime.mode,
            "telemetry": telemetry.model_dump(),
            "video": {
                "full_frame_ready": runtime.frame_store.latest_full_jpeg() is not None,
                "sampled_frame_ready": runtime.frame_store.latest_sampled_jpeg() is not None,
                "latest_sample": (
                    runtime.frame_store.latest_sampled_meta().model_dump()
                    if runtime.frame_store.latest_sampled_meta()
                    else None
                ),
            },
        }

    @app.post("/commands")
    async def command(command: DroneCommand):
        try:
            return await runtime.safety.execute(command)
        except ValueError as exc:
            result = CommandResult(
                command_id=command.command_id,
                status=CommandStatus.REJECTED,
                reason=str(exc),
            )
            await runtime.bus.publish("drone.command_results", result)
            return result

    @app.post("/operator-command")
    async def operator_command(command: OperatorCommand):
        handler = OperatorHandler(runtime.fsm, runtime.bus)
        return await handler.handle(command)

    @app.get("/frame/latest")
    async def latest_frame():
        frame = runtime.frame_store.latest_sampled_jpeg()
        if frame is None:
            raise HTTPException(status_code=404, detail="no sampled frame is available")
        return Response(frame, media_type="image/jpeg")

    @app.get("/video.mjpeg")
    async def mjpeg_video():
        return StreamingResponse(
            _mjpeg_generator(runtime.frame_store),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    @app.websocket("/events")
    async def events(websocket: WebSocket):
        await websocket.accept()
        topics = [
            "drone.telemetry",
            "drone.command_results",
            "drone.frames.llm",
            "drone.detections",
            "drone.state_change",
            "drone.paused",
            "drone.resumed",
            "drone.abort",
        ]
        queues = {topic: await runtime.bus.subscribe(topic) for topic in topics}
        tasks: set[asyncio.Task] = set()
        try:
            while True:
                if not tasks:
                    tasks = {
                        asyncio.create_task(queue.get(), name=topic)
                        for topic, queue in queues.items()
                    }
                done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    topic = task.get_name()
                    message = task.result()
                    payload = message.model_dump() if hasattr(message, "model_dump") else message
                    await websocket.send_text(json.dumps({"topic": topic, "message": payload}))
        except WebSocketDisconnect:
            pass
        finally:
            for task in tasks:
                task.cancel()
            for topic, queue in queues.items():
                await runtime.bus.unsubscribe(topic, queue)

    return app


async def _mjpeg_generator(frame_store: FrameStore):
    last_frame: bytes | None = None
    while True:
        frame = frame_store.latest_full_jpeg()
        if frame is not None and frame != last_frame:
            last_frame = frame
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(frame)).encode("ascii") + b"\r\n\r\n" + frame + b"\r\n"
            )
        await asyncio.sleep(0.05)
