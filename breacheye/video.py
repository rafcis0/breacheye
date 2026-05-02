from __future__ import annotations

import asyncio
import threading
from time import monotonic, time
from typing import Any

from breacheye.bus import AsyncEventBus
from breacheye.models import FrameMetadata


class FrameStore:
    """Stores one full-video frame path and one sampled frame path.

    The frontend can consume frequent/latest frames, while an LLM receives a
    slower sampled stream to control token and latency costs.
    """

    def __init__(self, sample_fps: float = 1.0, jpeg_quality: int = 75) -> None:
        self.sample_interval_s = 1.0 / sample_fps
        self.jpeg_quality = jpeg_quality
        self._latest_full_jpeg: bytes | None = None
        self._latest_sampled_jpeg: bytes | None = None
        self._latest_sampled_meta: FrameMetadata | None = None
        self._last_sample_at = 0.0
        self._sequence = 0
        self._lock = threading.Lock()

    def update_jpeg(self, data: bytes, width: int | None = None, height: int | None = None) -> FrameMetadata | None:
        with self._lock:
            self._latest_full_jpeg = data
            now = monotonic()
            if now - self._last_sample_at < self.sample_interval_s:
                return None
            self._last_sample_at = now
            self._sequence += 1
            meta = FrameMetadata(sequence=self._sequence, width=width, height=height, timestamp=time())
            self._latest_sampled_jpeg = data
            self._latest_sampled_meta = meta
            return meta

    def update_ndarray(self, frame: Any) -> FrameMetadata | None:
        jpeg = encode_jpeg(frame, quality=self.jpeg_quality)
        height = getattr(frame, "shape", [None, None])[0]
        width = getattr(frame, "shape", [None, None])[1]
        return self.update_jpeg(jpeg, width=width, height=height)

    def latest_full_jpeg(self) -> bytes | None:
        with self._lock:
            return self._latest_full_jpeg

    def latest_sampled_jpeg(self) -> bytes | None:
        with self._lock:
            return self._latest_sampled_jpeg

    def latest_sampled_meta(self) -> FrameMetadata | None:
        with self._lock:
            return self._latest_sampled_meta


def encode_jpeg(frame: Any, quality: int = 75) -> bytes:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("opencv-python is required to encode drone video frames") from exc

    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("failed to encode frame as JPEG")
    return encoded.tobytes()


class TelloVideoPump:
    def __init__(self, adapter, frame_store: FrameStore, bus: AsyncEventBus) -> None:
        self.adapter = adapter
        self.frame_store = frame_store
        self.bus = bus
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        await self.adapter.start_video()
        self._loop = asyncio.get_running_loop()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="tello-video-pump", daemon=True)
        self._thread.start()

    async def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            await asyncio.to_thread(self._thread.join, 2.0)
        await self.adapter.stop_video()

    def _run(self) -> None:
        reader = self.adapter.frame_reader()
        while not self._stop.is_set():
            frame = getattr(reader, "frame", None)
            if frame is None:
                self._stop.wait(0.03)
                continue
            try:
                meta = self.frame_store.update_ndarray(frame)
            except Exception:
                self._stop.wait(0.1)
                continue
            if meta is not None and self._loop is not None:
                asyncio.run_coroutine_threadsafe(
                    self.bus.publish("drone.frames.llm", meta),
                    self._loop,
                )
            self._stop.wait(0.03)
