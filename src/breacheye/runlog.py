from __future__ import annotations

import json
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from time import time
from typing import Any


class RunLogger:
    def __init__(self, component: str, log_dir: str | Path | None = None, run_id: str | None = None) -> None:
        self.component = component
        self.run_id = run_id or os.environ.get("BREACHEYE_RUN_ID") or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        root = Path(log_dir or os.environ.get("BREACHEYE_LOG_DIR", "logs")).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        self.path = root / f"{self.run_id}-{component}.jsonl"
        self.artifact_dir = root / self.run_id / component
        self._lock = threading.Lock()

    def event(self, event: str, **fields: Any) -> None:
        payload = {
            "ts": time(),
            "iso": datetime.now(UTC).isoformat(),
            "component": self.component,
            "run_id": self.run_id,
            "event": event,
            **_jsonable(fields),
        }
        line = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def save_bytes(self, category: str, name: str, data: bytes) -> Path:
        category_path = self.artifact_dir / _safe_path_part(category)
        filename = _safe_path_part(name)
        category_path.mkdir(parents=True, exist_ok=True)
        path = category_path / filename
        with self._lock:
            path.write_bytes(data)
        return path


def summarize_payload(payload: Any) -> dict[str, Any]:
    if hasattr(payload, "model_dump"):
        data = payload.model_dump(mode="python")
    elif isinstance(payload, dict):
        data = payload
    else:
        return {"type": type(payload).__name__}
    summary: dict[str, Any] = {"type": type(payload).__name__}
    for key in ("frame_id", "timestamp", "processing_ms", "pipeline_status"):
        if key in data:
            summary[key] = data[key]
    if "detections" in data:
        summary["detections_count"] = len(data["detections"])
    if "decision" in data and isinstance(data["decision"], dict):
        summary["action"] = data["decision"].get("action")
        summary["confidence"] = data["decision"].get("confidence")
    if "shape" in data:
        summary["shape"] = data["shape"]
    for key in ("jpeg_bytes", "depth_bytes"):
        if key in data:
            value = data[key]
            summary[f"{key}_len"] = len(value) if hasattr(value, "__len__") else None
    if "errors" in data:
        summary["errors_count"] = len(data["errors"])
    return summary


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    return repr(value)


def _safe_path_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return cleaned or "artifact"
