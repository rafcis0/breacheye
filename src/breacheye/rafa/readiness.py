from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CheckResult:
    name: str
    ready: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ready": self.ready, "detail": self.detail}


@dataclass(frozen=True)
class RafaReadiness:
    stub_checks: list[CheckResult] = field(default_factory=list)
    model_checks: list[CheckResult] = field(default_factory=list)

    @property
    def stub_ready(self) -> bool:
        return all(check.ready for check in self.stub_checks)

    @property
    def models_ready(self) -> bool:
        return all(check.ready for check in self.model_checks)

    def as_dict(self) -> dict[str, Any]:
        return {
            "stub_ready": self.stub_ready,
            "models_ready": self.models_ready,
            "stub_checks": [check.as_dict() for check in self.stub_checks],
            "model_checks": [check.as_dict() for check in self.model_checks],
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2)

    def to_text(self) -> str:
        lines = [
            f"stub_ready: {self.stub_ready}",
            f"models_ready: {self.models_ready}",
            "",
            "Stub checks:",
        ]
        lines.extend(_format_checks(self.stub_checks))
        lines.append("")
        lines.append("Model checks:")
        lines.extend(_format_checks(self.model_checks))
        return "\n".join(lines)


def check_rafa_readiness(repo_root: Path | None = None) -> RafaReadiness:
    root = repo_root or Path.cwd()
    return RafaReadiness(
        stub_checks=[
            _check_import("pyzmq", "zmq"),
            _check_import("msgpack", "msgpack"),
            _check_import("numpy", "numpy"),
            _check_import("opencv-python", "cv2"),
        ],
        model_checks=[
            _check_import("moondream", "moondream"),
            _check_existing_path("BREACHEYE_MOONDREAM_WEIGHTS", root),
            _check_import("Depth Anything V2", "depth_anything_v2"),
            _check_existing_path("BREACHEYE_DEPTH_ANYTHING_WEIGHTS", root),
            _check_qwen_vl(root),
            _check_optional_existing_path("BREACHEYE_SMOLVLM_PATH", root),
        ],
    )


def _check_import(label: str, module: str) -> CheckResult:
    if importlib.util.find_spec(module) is None:
        return CheckResult(label, False, f"Python module {module!r} is not installed")
    return CheckResult(label, True, f"Python module {module!r} is importable")


def _check_existing_path(env_var: str, repo_root: Path) -> CheckResult:
    value = os.environ.get(env_var)
    if not value:
        return CheckResult(env_var, False, f"{env_var} is not set")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    if not path.exists():
        return CheckResult(env_var, False, f"{path} does not exist")
    return CheckResult(env_var, True, str(path))


def _check_optional_existing_path(env_var: str, repo_root: Path) -> CheckResult:
    value = os.environ.get(env_var)
    if not value:
        return CheckResult(env_var, False, f"{env_var} is not set; optional fallback unavailable")
    return _check_existing_path(env_var, repo_root)


def _check_qwen_vl(repo_root: Path) -> CheckResult:
    server_url = os.environ.get("BREACHEYE_QWEN_SERVER_URL")
    env_path = os.environ.get("BREACHEYE_QWEN_MODEL")
    if env_path:
        path = Path(env_path).expanduser()
        if not path.is_absolute():
            path = repo_root / path
        projector_value = os.environ.get("BREACHEYE_QWEN_MMPROJ")
        if path.exists() and projector_value:
            projector = Path(projector_value).expanduser()
            if not projector.is_absolute():
                projector = repo_root / projector
            if not projector.exists():
                return CheckResult("qwen3_vl", False, f"BREACHEYE_QWEN_MMPROJ points to missing path {projector}")
            detail = f"BREACHEYE_QWEN_MODEL={path}; BREACHEYE_QWEN_MMPROJ={projector}"
            if server_url:
                detail += f"; BREACHEYE_QWEN_SERVER_URL={server_url}"
            return CheckResult("qwen3_vl", True, detail)
        if path.exists():
            return CheckResult("qwen3_vl", True, f"BREACHEYE_QWEN_MODEL={path}")
        return CheckResult("qwen3_vl", False, f"BREACHEYE_QWEN_MODEL points to missing path {path}")

    ollama_models = _ollama_models()
    vl_models = [name for name in ollama_models if "qwen" in name.lower() and "vl" in name.lower()]
    if vl_models:
        return CheckResult("qwen3_vl", True, f"Ollama VL model available: {', '.join(vl_models)}")
    if ollama_models:
        return CheckResult(
            "qwen3_vl",
            False,
            "Ollama is installed but no Qwen VL model is present; available: " + ", ".join(ollama_models),
        )
    return CheckResult("qwen3_vl", False, "No BREACHEYE_QWEN_MODEL path and no Ollama Qwen VL model found")


def _ollama_models() -> list[str]:
    try:
        result = subprocess.run(
            ["ollama", "list"],
            check=False,
            text=True,
            capture_output=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    names: list[str] = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if parts:
            names.append(parts[0])
    return names


def _format_checks(checks: list[CheckResult]) -> list[str]:
    return [f"- {'OK' if check.ready else 'MISSING'} {check.name}: {check.detail}" for check in checks]
