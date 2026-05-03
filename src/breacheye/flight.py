from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class FlightLaunchConfig:
    mode: str = "sim"
    rafa_mode: str = "stub"
    host: str = "127.0.0.1"
    port: int = 8000
    fps: float = 5.0
    log_dir: str = "logs"
    run_id: str | None = None
    frame_source: str = "auto"
    auto_takeoff: bool = False
    duration_s: float | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


@dataclass(frozen=True)
class ProcessSpec:
    name: str
    argv: list[str]


def build_process_specs(config: FlightLaunchConfig) -> list[ProcessSpec]:
    source = _resolve_frame_source(config)
    specs = [
        ProcessSpec(
            "harness",
            [
                sys.executable,
                "-m",
                "breacheye.cli",
                "serve",
                "--mode",
                config.mode,
                "--host",
                config.host,
                "--port",
                str(config.port),
            ],
        ),
        ProcessSpec(
            "rafa",
            [
                sys.executable,
                "-m",
                "breacheye.cli",
                "rafa",
                "--mode",
                config.rafa_mode,
                "--log-dir",
                config.log_dir,
                *(_run_id_args(config.run_id)),
            ],
        ),
        ProcessSpec(
            "frame_publisher",
            [
                sys.executable,
                str(_repo_root() / "integration" / "frame_publisher.py"),
                "--fps",
                str(config.fps),
                "--log-dir",
                config.log_dir,
                *(_run_id_args(config.run_id)),
                *(_frame_source_args(source, config)),
            ],
        ),
        ProcessSpec(
            "nav_interpreter",
            [
                sys.executable,
                "-m",
                "breacheye.cli",
                "nav",
                "--command-url",
                f"{config.base_url}/commands",
                "--log-dir",
                config.log_dir,
                *(_run_id_args(config.run_id)),
            ],
        ),
    ]
    return specs


def run_flight(config: FlightLaunchConfig) -> int:
    from breacheye.offline import write_preflight

    run_id = config.run_id or time.strftime("flight-%Y%m%dT%H%M%SZ", time.gmtime())
    config = FlightLaunchConfig(
        mode=config.mode,
        rafa_mode=config.rafa_mode,
        host=config.host,
        port=config.port,
        fps=config.fps,
        log_dir=config.log_dir,
        run_id=run_id,
        frame_source=config.frame_source,
        auto_takeoff=config.auto_takeoff,
        duration_s=config.duration_s,
    )
    os.environ["BREACHEYE_RUN_ID"] = run_id
    os.environ["BREACHEYE_LOG_DIR"] = config.log_dir
    write_preflight(log_dir=config.log_dir, run_id=run_id)

    procs: list[tuple[str, subprocess.Popen]] = []
    specs = build_process_specs(config)
    try:
        for spec in specs:
            print(f"[flight] starting {spec.name}: {' '.join(spec.argv)}", flush=True)
            procs.append((spec.name, subprocess.Popen(spec.argv, env=os.environ.copy())))
            if spec.name == "harness":
                _wait_for_harness(config.base_url)
            elif spec.name == "rafa":
                time.sleep(0.75)
            elif spec.name == "frame_publisher":
                time.sleep(0.5)

        if config.auto_takeoff:
            _post_takeoff(config.base_url)

        deadline = time.monotonic() + config.duration_s if config.duration_s else None
        while True:
            for name, proc in procs:
                code = proc.poll()
                if code is not None:
                    print(f"[flight] {name} exited with {code}", flush=True)
                    return code
            if deadline is not None and time.monotonic() >= deadline:
                print("[flight] duration reached; stopping", flush=True)
                return 0
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("[flight] interrupted; stopping", flush=True)
        return 130
    finally:
        _stop_processes(procs)


def _resolve_frame_source(config: FlightLaunchConfig) -> str:
    if config.frame_source != "auto":
        return config.frame_source
    return "harness" if config.mode == "tello" else "synthetic"


def _frame_source_args(source: str, config: FlightLaunchConfig) -> list[str]:
    if source == "harness":
        return ["--harness-url", f"{config.base_url}/frame/latest"]
    if source == "tello":
        return ["--tello"]
    if source == "synthetic":
        return []
    raise ValueError(f"unsupported frame source {source!r}")


def _run_id_args(run_id: str | None) -> list[str]:
    return ["--run-id", run_id] if run_id else []


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _wait_for_harness(base_url: str, timeout_s: float = 20.0) -> None:
    import httpx

    deadline = time.monotonic() + timeout_s
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base_url}/health", timeout=1.0)
            if response.status_code == 200:
                return
        except Exception as exc:
            last_error = exc
        time.sleep(0.25)
    raise RuntimeError(f"harness did not become ready at {base_url}: {last_error}")


def _post_takeoff(base_url: str) -> None:
    import httpx

    response = httpx.post(
        f"{base_url}/commands",
        json={"type": "takeoff", "issued_by": "flight_launcher"},
        timeout=5.0,
    )
    response.raise_for_status()
    print(f"[flight] takeoff response: {response.text}", flush=True)


def _stop_processes(procs: Sequence[tuple[str, subprocess.Popen]]) -> None:
    for name, proc in reversed(procs):
        if proc.poll() is not None:
            continue
        print(f"[flight] stopping {name}", flush=True)
        proc.terminate()
    deadline = time.monotonic() + 5.0
    for _name, proc in reversed(procs):
        remaining = max(0.1, deadline - time.monotonic())
        try:
            proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            proc.terminate()
    for _name, proc in reversed(procs):
        if proc.poll() is None:
            proc.kill()
