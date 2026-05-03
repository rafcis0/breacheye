from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from breacheye.runlog import RunLogger

_COMPONENTS = ("frame_publisher", "rafa", "nav_interpreter", "map_builder")


@dataclass
class JsonlTailer:
    path: Path
    offset: int = 0

    def read_new(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as handle:
            handle.seek(self.offset)
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    rows.append({"component": self.path.stem, "event": "json_decode_failed", "raw": line[:500]})
            self.offset = handle.tell()
        return rows


def monitor_run(
    *,
    log_dir: str | Path = "logs",
    run_id: str | None = "latest",
    harness_url: str = "http://127.0.0.1:8000",
    interval_s: float = 1.0,
    frame_interval_s: float = 2.0,
    duration_s: float | None = None,
    save_frames: bool = True,
) -> int:
    log_root = Path(log_dir).expanduser()
    harness_url = harness_url.rstrip("/")
    deadline = time.monotonic() + duration_s if duration_s else None
    active_run_id: str | None = None
    logger: RunLogger | None = None
    tailers: dict[str, JsonlTailer] = {}
    last_health_at = 0.0
    last_frame_at = 0.0
    frame_sample_id = 0
    last_line_by_key: dict[str, str] = {}

    try:
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                return 0

            resolved = resolve_run_id(log_root, run_id)
            if resolved and resolved != active_run_id:
                active_run_id = resolved
                logger = RunLogger("monitor", log_dir=log_root, run_id=active_run_id)
                logger.event("monitor_start", harness_url=harness_url)
                tailers = {
                    component: JsonlTailer(log_root / f"{active_run_id}-{component}.jsonl")
                    for component in _COMPONENTS
                }
                print(f"[monitor] run_id={active_run_id}", flush=True)

            if tailers:
                for component, tailer in tailers.items():
                    for row in tailer.read_new():
                        line = summarize_event(row)
                        if line:
                            print(line, flush=True)
                            if logger is not None:
                                logger.event("timeline_observed", source_component=component, line=line, source=row)

            now = time.monotonic()
            if now - last_health_at >= max(0.25, interval_s):
                last_health_at = now
                _poll_health(harness_url, logger, last_line_by_key)

            if now - last_frame_at >= max(0.25, frame_interval_s):
                last_frame_at = now
                frame_sample_id += 1
                _poll_frame(harness_url, logger, frame_sample_id, save_frames, last_line_by_key)

            time.sleep(max(0.1, min(interval_s, frame_interval_s, 1.0)))
    except KeyboardInterrupt:
        if logger is not None:
            logger.event("monitor_stop", reason="keyboard_interrupt")
        return 130


def resolve_run_id(log_dir: Path, requested: str | None) -> str | None:
    if requested and requested != "latest":
        return requested
    if requested is None and os.environ.get("BREACHEYE_RUN_ID"):
        return os.environ["BREACHEYE_RUN_ID"]
    candidates: list[Path] = []
    for component in _COMPONENTS:
        candidates.extend(log_dir.glob(f"*-{component}.jsonl"))
    if not candidates:
        return None
    newest = max(candidates, key=lambda path: path.stat().st_mtime)
    for suffix in [f"-{component}.jsonl" for component in _COMPONENTS]:
        if newest.name.endswith(suffix):
            return newest.name[: -len(suffix)]
    return None


def summarize_event(row: dict[str, Any]) -> str | None:
    component = row.get("component", "?")
    event = row.get("event", "?")

    if component == "frame_publisher":
        if event == "frame_published":
            return f"[frame] published id={row.get('frame_id')} size={row.get('width')}x{row.get('height')} bytes={row.get('jpeg_bytes')}"
        if event == "harness_frame_skipped":
            return f"[frame] skipped reason={row.get('reason')} size={row.get('width')}x{row.get('height')} luma={row.get('mean_luma')}"

    if component == "rafa":
        if event == "frame_received":
            return f"[rafa] frame id={row.get('frame_id')} size={row.get('width')}x{row.get('height')} bytes={row.get('jpeg_bytes')}"
        if event == "navigation_context_built":
            summary = row.get("summary", {})
            return (
                f"[context] frame={row.get('frame_id')} nearest={summary.get('nearest_obstacle_m')}m "
                f"objects={summary.get('known_objects')} frontiers={summary.get('frontiers')} recent={summary.get('recent_actions')}"
            )
        if event == "navigation_decision_built":
            return (
                f"[decision] frame={row.get('frame_id')} action={row.get('action')} "
                f"conf={row.get('confidence')} reason={_short(row.get('reasoning'))}"
            )
        if event == "frame_pipeline_summary":
            return (
                f"[latency] frame={row.get('frame_id')} total={row.get('total_ms')}ms "
                f"detect={row.get('detection_ms')} depth={row.get('depth_ms')} nav={row.get('navigation_ms')}"
            )
        if event == "publish" and row.get("channel") == "health":
            summary = row.get("summary", {})
            return f"[rafa-health] status={summary.get('pipeline_status')} errors={summary.get('errors_count')}"
        if event == "model_fallback":
            return f"[model] fallback model={row.get('model')} fallback={row.get('fallback')} error={_short(row.get('error'))}"

    if component == "nav_interpreter":
        if event == "navigation_received":
            return (
                f"[nav] received frame={row.get('frame_id')} action={row.get('action')} "
                f"conf={row.get('confidence')} reason={_short(row.get('reasoning'))}"
            )
        if event == "command_posted":
            return (
                f"[cmd] type={row.get('command_type')} status={row.get('response_status')} "
                f"reason={_short(row.get('response_reason'))} payload={row.get('command_payload')}"
            )
        if event == "navigation_executed":
            return f"[nav] executed frame={row.get('frame_id')} command={row.get('command_type')} id={row.get('command_id')}"
        if event.endswith("_failed") or event.endswith("_grounded") or event == "navigation_low_confidence":
            return f"[nav] {event} frame={row.get('frame_id')} reason={_short(row.get('reasoning') or row.get('error'))}"

    if component == "map_builder":
        if event == "map_updated":
            stats = row.get("stats", {})
            return f"[map] points={stats.get('points')} frames={stats.get('frames_used')} source={row.get('source')}"
        if event == "map_builder_warning":
            return f"[map] warning={_short(row.get('error'))}"

    return None


def jpeg_stats(jpeg_bytes: bytes) -> dict[str, Any]:
    import cv2
    import numpy as np

    data = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("undecodable JPEG")
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return {
        "width": int(frame.shape[1]),
        "height": int(frame.shape[0]),
        "jpeg_bytes": len(jpeg_bytes),
        "mean_luma": round(float(gray.mean()), 3),
        "luma_stddev": round(float(gray.std()), 3),
        "blur_laplacian_var": round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 3),
    }


def _poll_health(harness_url: str, logger: RunLogger | None, last_line_by_key: dict[str, str]) -> None:
    try:
        import httpx

        response = httpx.get(f"{harness_url}/health", timeout=1.0)
        response.raise_for_status()
        payload = response.json()
        telemetry = payload.get("telemetry", {})
        raw = telemetry.get("raw") or {}
        video = payload.get("video", {})
        line = (
            f"[health] connected={telemetry.get('connected')} flying={telemetry.get('flying')} "
            f"bat={telemetry.get('battery')} height={telemetry.get('height_cm')} tof={raw.get('tof')} "
            f"pitch={raw.get('pitch')} roll={raw.get('roll')} video={video.get('running')} "
            f"sample={video.get('sampled_frame_ready')}"
        )
        _print_if_changed("health", line, last_line_by_key)
        if logger is not None:
            logger.event("harness_health", telemetry=telemetry, video=video)
    except Exception as exc:
        line = f"[health] unavailable error={_short(str(exc))}"
        _print_if_changed("health", line, last_line_by_key)
        if logger is not None:
            logger.event("harness_health_failed", error=str(exc))


def _poll_frame(
    harness_url: str,
    logger: RunLogger | None,
    sample_id: int,
    save_frames: bool,
    last_line_by_key: dict[str, str],
) -> None:
    try:
        import httpx

        response = httpx.get(f"{harness_url}/frame/latest", timeout=1.0)
        if response.status_code == 404:
            _print_if_changed("frame-latest", "[stream] no sampled frame yet", last_line_by_key)
            return
        response.raise_for_status()
        stats = jpeg_stats(response.content)
        image_path = None
        if logger is not None and save_frames:
            image_path = logger.save_bytes("frames", f"sample-{sample_id:08d}.jpg", response.content)
        line = (
            f"[stream] frame size={stats['width']}x{stats['height']} luma={stats['mean_luma']} "
            f"std={stats['luma_stddev']} blur={stats['blur_laplacian_var']}"
        )
        print(line, flush=True)
        if logger is not None:
            logger.event("harness_frame_sample", sample_id=sample_id, image_path=image_path, **stats)
    except Exception as exc:
        line = f"[stream] unavailable error={_short(str(exc))}"
        _print_if_changed("frame-latest", line, last_line_by_key)
        if logger is not None:
            logger.event("harness_frame_sample_failed", sample_id=sample_id, error=str(exc))


def _print_if_changed(key: str, line: str, last_line_by_key: dict[str, str]) -> None:
    if last_line_by_key.get(key) == line:
        return
    last_line_by_key[key] = line
    print(line, flush=True)


def _short(value: Any, limit: int = 140) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
