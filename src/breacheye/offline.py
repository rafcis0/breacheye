from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from breacheye.runlog import RunLogger


INTERESTING_ENV = (
    "BREACHEYE_RUN_ID",
    "BREACHEYE_LOG_DIR",
    "BREACHEYE_QWEN_MODEL",
    "BREACHEYE_QWEN_MMPROJ",
    "BREACHEYE_QWEN_SERVER_URL",
    "BREACHEYE_QWEN_MAX_TOKENS",
    "BREACHEYE_DEPTH_ANYTHING_PATH",
    "BREACHEYE_DEPTH_ANYTHING_DEVICE",
    "BREACHEYE_MOONDREAM_WEIGHTS",
    "BREACHEYE_SMOLVLM_PATH",
)

DEFAULT_PORTS = {
    "frame_input": 5555,
    "detections": 5556,
    "depth": 5557,
    "navigation": 5558,
    "health": 5559,
    "harness_api": 8000,
    "qwen_server": 56262,
}


@dataclass(frozen=True)
class OfflinePaths:
    log_dir: Path
    run_id: str

    @property
    def run_dir(self) -> Path:
        return self.log_dir / self.run_id

    @property
    def metadata_path(self) -> Path:
        return self.run_dir / "run-metadata.json"

    @property
    def bundle_path(self) -> Path:
        return self.log_dir / f"{self.run_id}-offline-bundle.tar.gz"


def offline_paths(log_dir: str | Path = "logs", run_id: str | None = None) -> OfflinePaths:
    resolved_run_id = run_id or os.environ.get("BREACHEYE_RUN_ID") or datetime.now(UTC).strftime("offline-%Y%m%dT%H%M%SZ")
    return OfflinePaths(Path(log_dir or os.environ.get("BREACHEYE_LOG_DIR", "logs")).expanduser(), resolved_run_id)


def write_preflight(log_dir: str | Path = "logs", run_id: str | None = None) -> Path:
    paths = offline_paths(log_dir=log_dir, run_id=run_id)
    paths.run_dir.mkdir(parents=True, exist_ok=True)
    payload = collect_preflight(paths)
    paths.metadata_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    logger = RunLogger("offline", log_dir=paths.log_dir, run_id=paths.run_id)
    logger.event(
        "offline_preflight",
        metadata_path=paths.metadata_path,
        qwen_server=payload["ports"]["qwen_server"],
        frame_input=payload["ports"]["frame_input"],
        disk_free_bytes=payload["disk"]["free_bytes"],
    )
    return paths.metadata_path


def collect_preflight(paths: OfflinePaths) -> dict[str, Any]:
    env = {name: os.environ.get(name) for name in INTERESTING_ENV if os.environ.get(name)}
    return {
        "run_id": paths.run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "cwd": str(Path.cwd()),
        "python": {
            "version": platform.python_version(),
            "executable": shutil.which("python") or "",
            "platform": platform.platform(),
        },
        "git": _git_state(),
        "env": env,
        "env_paths": {name: _path_state(value) for name, value in env.items() if _looks_like_path(value)},
        "commands": {
            "breacheye": shutil.which("breacheye"),
            "llama-server": shutil.which("llama-server"),
            "llama-mtmd-cli": shutil.which("llama-mtmd-cli"),
            "python": shutil.which("python"),
        },
        "ports": {name: _port_state(port) for name, port in DEFAULT_PORTS.items()},
        "processes": _interesting_processes(),
        "disk": _disk_state(paths.log_dir),
        "artifacts": _artifact_state(paths),
    }


def create_bundle(log_dir: str | Path = "logs", run_id: str | None = None) -> Path:
    paths = offline_paths(log_dir=log_dir, run_id=run_id)
    paths.log_dir.mkdir(parents=True, exist_ok=True)
    if not paths.metadata_path.exists():
        write_preflight(log_dir=paths.log_dir, run_id=paths.run_id)
    with tarfile.open(paths.bundle_path, "w:gz") as archive:
        for path in _bundle_members(paths):
            archive.add(path, arcname=path.relative_to(paths.log_dir))
    logger = RunLogger("offline", log_dir=paths.log_dir, run_id=paths.run_id)
    logger.event("offline_bundle_created", bundle_path=paths.bundle_path)
    return paths.bundle_path


def _bundle_members(paths: OfflinePaths) -> list[Path]:
    members: list[Path] = []
    for path in sorted(paths.log_dir.glob(f"{paths.run_id}-*.jsonl")):
        if path.is_file():
            members.append(path)
    if paths.run_dir.exists():
        members.extend(path for path in sorted(paths.run_dir.rglob("*")) if path.is_file())
    return members


def _artifact_state(paths: OfflinePaths) -> dict[str, Any]:
    run_files = [path for path in paths.run_dir.rglob("*") if path.is_file()] if paths.run_dir.exists() else []
    jsonl_files = sorted(paths.log_dir.glob(f"{paths.run_id}-*.jsonl")) if paths.log_dir.exists() else []
    return {
        "run_dir": str(paths.run_dir),
        "metadata_path": str(paths.metadata_path),
        "jsonl_files": [str(path) for path in jsonl_files],
        "run_file_count": len(run_files),
        "frame_count": len([path for path in run_files if "/frames/" in path.as_posix() and path.suffix.lower() in {".jpg", ".jpeg"}]),
        "depth_image_count": len([path for path in run_files if "/depth/" in path.as_posix() and path.suffix.lower() == ".png"]),
    }


def _git_state() -> dict[str, Any]:
    return {
        "commit": _run_text(["git", "rev-parse", "HEAD"]),
        "branch": _run_text(["git", "branch", "--show-current"]),
        "status_short": _run_text(["git", "status", "--short"]),
    }


def _disk_state(path: Path) -> dict[str, int | str]:
    path.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(path)
    return {
        "path": str(path),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
    }


def _interesting_processes() -> list[str]:
    output = _run_text(["pgrep", "-af", "llama-server|breacheye rafa|frame_publisher|zmq_test_sub"])
    return [line for line in output.splitlines() if line.strip()]


def _path_state(value: str) -> dict[str, Any]:
    path = Path(value).expanduser()
    exists = path.exists()
    return {
        "path": str(path),
        "exists": exists,
        "is_file": path.is_file() if exists else False,
        "is_dir": path.is_dir() if exists else False,
        "bytes": path.stat().st_size if path.is_file() else None,
    }


def _looks_like_path(value: str) -> bool:
    return "/" in value or value.startswith(".") or value.startswith("~")


def _port_state(port: int, host: str = "127.0.0.1") -> dict[str, Any]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.15)
        listening = sock.connect_ex((host, port)) == 0
    return {"host": host, "port": port, "listening": listening}


def _run_text(command: list[str]) -> str:
    try:
        completed = subprocess.run(command, text=True, capture_output=True, timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (completed.stdout or completed.stderr).strip()
