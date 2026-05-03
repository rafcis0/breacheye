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
    _apply_local_model_defaults(os.environ, config.rafa_mode)
    write_preflight(log_dir=config.log_dir, run_id=run_id)

    procs: list[tuple[str, subprocess.Popen]] = []
    specs = build_process_specs(config)
    try:
        for spec in specs:
            print(f"[flight] starting {spec.name}: {' '.join(spec.argv)}", flush=True)
            procs.append((spec.name, subprocess.Popen(spec.argv, env=os.environ.copy(), start_new_session=True)))
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
        _stop_flight_processes(procs, config.base_url)


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


def _apply_local_model_defaults(env: dict[str, str], rafa_mode: str) -> None:
    if rafa_mode != "models":
        return
    root = _repo_root()
    defaults = {
        "BREACHEYE_QWEN_MODEL": root / "models/qwen3-vl-2b/Qwen3-VL-2B-Instruct-Q4_K_M.gguf",
        "BREACHEYE_QWEN_MMPROJ": root / "models/qwen3-vl-2b/mmproj-F16.gguf",
        "BREACHEYE_DEPTH_ANYTHING_PATH": root / "models/depth-anything-v2-small-hf",
        "BREACHEYE_SMOLVLM_PATH": root / "models/smolvlm2-500m",
    }
    for key, path in defaults.items():
        if key not in env and path.exists():
            env[key] = str(path)
    if "BREACHEYE_DEPTH_ANYTHING_DEVICE" not in env:
        env["BREACHEYE_DEPTH_ANYTHING_DEVICE"] = "mps"
    if "BREACHEYE_QWEN_SERVER_URL" not in env and _qwen_server_available():
        env["BREACHEYE_QWEN_SERVER_URL"] = "http://127.0.0.1:56262"
    if "BREACHEYE_QWEN_MAX_TOKENS" not in env:
        env["BREACHEYE_QWEN_MAX_TOKENS"] = "32"


def _qwen_server_available(url: str = "http://127.0.0.1:56262") -> bool:
    try:
        import urllib.request

        with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=0.25):
            return True
    except Exception:
        return False


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


def _post_shutdown_land(base_url: str) -> None:
    import httpx

    try:
        health = httpx.get(f"{base_url}/health", timeout=1.5)
        if health.status_code == 200 and not health.json().get("telemetry", {}).get("flying"):
            print("[flight] drone already grounded", flush=True)
            return
    except Exception as exc:
        print(f"[flight] could not read health before landing: {exc}", flush=True)

    for command_type in ("hover", "land"):
        try:
            response = httpx.post(
                f"{base_url}/commands",
                json={"type": command_type, "issued_by": "flight_launcher_shutdown"},
                timeout=8.0,
            )
            print(f"[flight] shutdown {command_type} response: {response.text}", flush=True)
        except Exception as exc:
            print(f"[flight] shutdown {command_type} failed: {exc}", flush=True)
        time.sleep(0.25)


def _stop_flight_processes(procs: Sequence[tuple[str, subprocess.Popen]], base_url: str) -> None:
    non_harness = [(name, proc) for name, proc in procs if name != "harness"]
    harness = [(name, proc) for name, proc in procs if name == "harness"]
    _stop_processes(non_harness)
    if harness and harness[0][1].poll() is None:
        _post_shutdown_land(base_url)
    _stop_processes(harness)


def build_demo_specs(
    mode: str,
    host: str = "127.0.0.1",
    port: int = 8000,
    fps: float = 5.0,
    video_path: str | None = None,
    log_dir: str = "logs",
    run_id: str | None = None,
) -> list[ProcessSpec]:
    base_url = f"http://{host}:{port}"
    root = _repo_root()
    specs: list[ProcessSpec] = []

    # Harness is always first
    harness_mode = "tello" if mode == "live" else "sim"
    specs.append(ProcessSpec(
        "harness",
        [sys.executable, "-m", "breacheye.cli", "serve",
         "--mode", harness_mode, "--host", host, "--port", str(port)],
    ))

    if mode == "live":
        specs.append(ProcessSpec(
            "rafa",
            [sys.executable, "-m", "breacheye.cli", "rafa",
             "--mode", "models", "--log-dir", log_dir, *_run_id_args(run_id)],
        ))
        specs.append(ProcessSpec(
            "frame_publisher",
            [sys.executable, str(root / "integration" / "frame_publisher.py"),
             "--fps", str(fps), "--tello", "--log-dir", log_dir, *_run_id_args(run_id)],
        ))
    elif mode == "recorded":
        playback_args = [
            sys.executable, str(root / "demo" / "playback.py"),
            "--video", video_path or str(root / "demo" / "sample.mp4"),
            "--detections", str(root / "demo" / "mock_detections.json"),
            "--loop",
        ]
        if fps:
            playback_args.extend(["--fps", str(fps)])
        specs.append(ProcessSpec("playback", playback_args))
        specs.append(ProcessSpec(
            "mock_navigation",
            [sys.executable, str(root / "demo" / "mock_navigation.py"),
             "--frames", "999999", "--pattern", "room_sweep", "--fps", "2"],
        ))
        specs.append(ProcessSpec(
            "mock_telemetry",
            [sys.executable, str(root / "demo" / "mock_telemetry.py"),
             "--frames", "999999", "--fps", "1"],
        ))
    elif mode == "mock":
        specs.append(ProcessSpec(
            "frame_publisher",
            [sys.executable, str(root / "integration" / "frame_publisher.py"),
             "--fps", str(fps), "--log-dir", log_dir, *_run_id_args(run_id)],
        ))
        specs.append(ProcessSpec(
            "mock_detections",
            [sys.executable, str(root / "demo" / "mock_detections.py"),
             "--frames", "999999", "--fps", "10"],
        ))
        specs.append(ProcessSpec(
            "mock_navigation",
            [sys.executable, str(root / "demo" / "mock_navigation.py"),
             "--frames", "999999", "--pattern", "room_sweep", "--fps", "2"],
        ))
        specs.append(ProcessSpec(
            "mock_telemetry",
            [sys.executable, str(root / "demo" / "mock_telemetry.py"),
             "--frames", "999999", "--fps", "1"],
        ))

    # Nav interpreter in ALL modes — bridges ZMQ 5558 → harness /commands
    specs.append(ProcessSpec(
        "nav_interpreter",
        [sys.executable, "-m", "breacheye.cli", "nav",
         "--command-url", f"{base_url}/commands", "--log-dir", log_dir, *_run_id_args(run_id)],
    ))

    return specs


def run_demo(
    mode: str = "live",
    host: str = "127.0.0.1",
    port: int = 8000,
    fps: float = 5.0,
    video_path: str | None = None,
    log_dir: str = "logs",
    run_id: str | None = None,
    duration_s: float | None = None,
) -> int:
    run_id = run_id or time.strftime("demo-%Y%m%dT%H%M%SZ", time.gmtime())
    resolved_mode = _resolve_demo_mode(mode, video_path)

    print(f"\n{'=' * 60}", flush=True)
    print(f"  BreachEye Demo — mode: {resolved_mode}", flush=True)
    if resolved_mode != mode:
        print(f"  (auto-degraded from {mode})", flush=True)
    print(f"  harness: http://{host}:{port}", flush=True)
    print(f"{'=' * 60}\n", flush=True)

    base_url = f"http://{host}:{port}"
    os.environ["BREACHEYE_RUN_ID"] = run_id
    os.environ["BREACHEYE_LOG_DIR"] = log_dir
    if resolved_mode == "live":
        _apply_local_model_defaults(os.environ, "models")

    specs = build_demo_specs(resolved_mode, host, port, fps, video_path, log_dir, run_id)
    procs: list[tuple[str, subprocess.Popen]] = []

    try:
        for spec in specs:
            print(f"[demo] starting {spec.name}", flush=True)
            procs.append((spec.name, subprocess.Popen(spec.argv, env=os.environ.copy(), start_new_session=True)))
            if spec.name == "harness":
                _wait_for_harness(base_url)
            elif spec.name in ("rafa", "playback"):
                time.sleep(0.75)
            elif spec.name == "frame_publisher":
                time.sleep(0.5)

        print("\n[demo] all components running — Ctrl+C to stop\n", flush=True)

        deadline = time.monotonic() + duration_s if duration_s else None
        while True:
            for name, proc in procs:
                code = proc.poll()
                if code is not None:
                    print(f"[demo] {name} exited with {code}", flush=True)
                    return code
            if deadline and time.monotonic() >= deadline:
                print("[demo] duration reached; stopping", flush=True)
                return 0
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[demo] interrupted; stopping", flush=True)
        return 130
    finally:
        _stop_flight_processes(procs, base_url)


def _resolve_demo_mode(mode: str, video_path: str | None) -> str:
    if mode == "live":
        if not _check_tello_connection():
            print("[demo] WARNING: Tello not available — falling back to recorded mode", flush=True)
            mode = "recorded"
    if mode == "recorded":
        vpath = video_path or str(_repo_root() / "demo" / "sample.mp4")
        if not Path(vpath).exists():
            print(f"[demo] WARNING: video not found ({vpath}) — falling back to mock mode", flush=True)
            mode = "mock"
    return mode


def _check_tello_connection(timeout: float = 5.0) -> bool:
    """Try connecting to Tello. Returns True if successful within timeout."""
    try:
        result = subprocess.run(
            [sys.executable, "-c",
             "from djitellopy import Tello; t = Tello(); t.connect(); print('ok')"],
            capture_output=True, text=True, timeout=timeout,
        )
        return result.returncode == 0 and "ok" in result.stdout
    except (subprocess.TimeoutExpired, Exception):
        return False


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
        except KeyboardInterrupt:
            proc.terminate()
    for _name, proc in reversed(procs):
        if proc.poll() is None:
            proc.kill()
