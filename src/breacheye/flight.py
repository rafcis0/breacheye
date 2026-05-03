from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


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
    takeoff_climb_cm: int = 100
    duration_s: float | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


@dataclass(frozen=True)
class ProcessSpec:
    name: str
    argv: list[str]
    post_takeoff: bool = False


def build_process_specs(config: FlightLaunchConfig) -> list[ProcessSpec]:
    source = _resolve_frame_source(config)
    harness = ProcessSpec(
        "harness",
        _harness_argv(
            config.mode,
            config.host,
            config.port,
            defer_video=config.mode == "tello" and config.auto_takeoff,
        ),
    )
    background = [
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
            post_takeoff=True,
        ),
        ProcessSpec(
            "map_builder",
            [
                sys.executable,
                str(_repo_root() / "integration" / "map_builder.py"),
                "--log-dir",
                config.log_dir,
                *(_run_id_args(config.run_id)),
            ],
            post_takeoff=True,
        ),
    ]
    if config.mode == "tello" and config.auto_takeoff:
        return [*background, harness]
    return [harness, *background]


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
        takeoff_climb_cm=config.takeoff_climb_cm,
        duration_s=config.duration_s,
    )
    os.environ["BREACHEYE_RUN_ID"] = run_id
    os.environ["BREACHEYE_LOG_DIR"] = config.log_dir
    _apply_live_safety_defaults(os.environ, mode=config.mode, auto_takeoff=config.auto_takeoff)
    _apply_local_model_defaults(os.environ, config.rafa_mode)
    write_preflight(log_dir=config.log_dir, run_id=run_id)

    procs: list[tuple[str, subprocess.Popen]] = []
    specs = build_process_specs(config)
    pre_specs = [s for s in specs if not s.post_takeoff]
    post_specs = [s for s in specs if s.post_takeoff]
    try:
        for spec in pre_specs:
            print(f"[flight] starting {spec.name}: {' '.join(spec.argv)}", flush=True)
            procs.append((spec.name, subprocess.Popen(spec.argv, env=os.environ.copy(), start_new_session=True)))
            if spec.name == "harness":
                _wait_for_harness(config.base_url)
            elif spec.name == "rafa":
                time.sleep(0.75)
            elif spec.name == "frame_publisher":
                time.sleep(0.5)

        if config.auto_takeoff:
            if config.mode == "tello":
                _wait_for_takeoff_preflight(config.base_url, prefix="[flight]")
            _post_takeoff(
                config.base_url,
                climb_cm=config.takeoff_climb_cm,
                after_takeoff=(
                    lambda: _start_harness_video(config.base_url, prefix="[flight]")
                    if config.mode == "tello"
                    else None
                ),
            )
            _wait_for_accepts_nav(config.base_url, prefix="[flight]")

        for spec in post_specs:
            print(f"[flight] starting {spec.name}: {' '.join(spec.argv)}", flush=True)
            procs.append((spec.name, subprocess.Popen(spec.argv, env=os.environ.copy(), start_new_session=True)))

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
    except Exception as exc:
        print(f"[flight] launch failed: {exc}", flush=True)
        return 1
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


def _harness_argv(mode: str, host: str, port: int, *, defer_video: bool = False) -> list[str]:
    argv = [
        sys.executable,
        "-m",
        "breacheye.cli",
        "serve",
        "--mode",
        mode,
        "--host",
        host,
        "--port",
        str(port),
    ]
    if defer_video:
        argv.append("--defer-video")
    return argv


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


def _apply_live_safety_defaults(env: dict[str, str], *, mode: str, auto_takeoff: bool) -> None:
    if auto_takeoff and mode in {"live", "tello"}:
        env.setdefault("BREACHEYE_STABILIZER_MODE", "log")


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


def _wait_for_takeoff_preflight(
    base_url: str,
    *,
    prefix: str,
    timeout_s: float = 8.0,
    min_battery: int | None = None,
) -> None:
    import httpx

    min_battery = _env_int("BREACHEYE_TELLO_MIN_TAKEOFF_BATTERY", min_battery or 25, minimum=1, maximum=100)
    deadline = time.monotonic() + timeout_s
    last_payload: dict | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base_url}/health", timeout=1.0)
            if response.status_code == 200:
                last_payload = response.json()
                telemetry = last_payload.get("telemetry", {})
                battery = telemetry.get("battery")
                connected = telemetry.get("connected")
                if connected is True and battery is not None:
                    print(f"{prefix} takeoff preflight: {_health_summary_from_telemetry(telemetry)}", flush=True)
                    if battery < min_battery:
                        raise RuntimeError(
                            f"refusing auto-takeoff: battery {battery}% is below {min_battery}% minimum"
                        )
                    return
        except RuntimeError:
            raise
        except Exception:
            pass
        time.sleep(0.25)
    summary = _health_summary_from_telemetry((last_payload or {}).get("telemetry", {}))
    raise RuntimeError(f"refusing auto-takeoff: telemetry was not ready ({summary})")


def _post_takeoff(
    base_url: str,
    climb_cm: int = 100,
    after_takeoff: Callable[[], None] | None = None,
) -> None:
    if _wait_for_flying(base_url, timeout_s=0.1):
        print("[flight] drone already reports flying; skipping takeoff command", flush=True)
        if after_takeoff is not None:
            after_takeoff()
        return

    _post_command_checked(
        base_url,
        {"type": "takeoff", "issued_by": "flight_launcher"},
        label="takeoff",
    )
    if after_takeoff is not None:
        after_takeoff()

    climb_cm = max(0, min(150, int(climb_cm)))
    if climb_cm <= 0:
        return
    if not _wait_for_flying(base_url):
        print("[flight] skipping takeoff climb; harness did not report flying", flush=True)
        return

    speed_cm_s = 30
    remaining_cm = climb_cm
    pulse_index = 0
    while remaining_cm > 0:
        pulse_index += 1
        pulse_cm = min(30, remaining_cm)
        duration_ms = max(300, min(1000, int(pulse_cm / speed_cm_s * 1000)))
        _post_command_checked(
            base_url,
            {
                "type": "rc_control",
                "issued_by": "flight_launcher_takeoff_climb",
                "ttl_ms": duration_ms + 200,
                "payload": {"up_down": speed_cm_s, "duration_ms": duration_ms},
            },
            label=f"takeoff climb pulse {pulse_index} {pulse_cm}cm/{climb_cm}cm",
        )
        remaining_cm -= pulse_cm
        time.sleep(0.15)


def _start_harness_video(base_url: str, *, prefix: str) -> None:
    import httpx

    response = httpx.post(f"{base_url}/video/start", timeout=10.0)
    response.raise_for_status()
    print(f"{prefix} video start response: {response.text}", flush=True)


def _post_command_checked(base_url: str, command: dict, *, label: str) -> dict:
    import httpx

    response = httpx.post(
        f"{base_url}/commands",
        json=command,
        timeout=_command_timeout_s(command),
    )
    response.raise_for_status()
    print(f"[flight] {label} response: {response.text}", flush=True)
    payload = response.json()
    if payload.get("status") != "executed":
        reason = payload.get("reason") or payload.get("status") or "unknown failure"
        health = _harness_health_summary(base_url)
        if health:
            reason = f"{reason}; harness health: {health}"
        raise RuntimeError(f"{label} failed: {reason}")
    return payload


def _command_timeout_s(command: dict) -> float:
    command_type = command.get("type")
    if command_type in {"takeoff", "land", "emergency"}:
        return 30.0
    return 5.0


def _harness_health_summary(base_url: str) -> str | None:
    import httpx

    try:
        response = httpx.get(f"{base_url}/health", timeout=1.5)
        response.raise_for_status()
        telemetry = response.json().get("telemetry", {})
    except Exception:
        return None

    return _health_summary_from_telemetry(telemetry)


def _health_summary_from_telemetry(telemetry: dict) -> str:
    raw = telemetry.get("raw") or {}
    fields = {
        "connected": telemetry.get("connected"),
        "flying": telemetry.get("flying"),
        "battery": telemetry.get("battery"),
        "height_cm": telemetry.get("height_cm"),
        "flight_time_s": telemetry.get("flight_time_s"),
        "tof": raw.get("tof"),
        "templ": raw.get("templ"),
        "temph": raw.get("temph"),
        "pitch": raw.get("pitch"),
        "roll": raw.get("roll"),
    }
    return ", ".join(f"{key}={value}" for key, value in fields.items())


def _wait_for_flying(base_url: str, timeout_s: float = 5.0) -> bool:
    import httpx

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base_url}/health", timeout=1.0)
            if response.status_code == 200 and response.json().get("telemetry", {}).get("flying"):
                return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


def _post_shutdown_land(base_url: str) -> None:
    import httpx

    try:
        health = httpx.get(f"{base_url}/health", timeout=1.5)
        if health.status_code == 200 and not health.json().get("telemetry", {}).get("flying"):
            print("[flight] drone already grounded", flush=True)
            return
    except Exception as exc:
        print(f"[flight] could not read health before landing: {exc}", flush=True)

    land_failed = False
    for command_type in ("hover", "land"):
        try:
            response = httpx.post(
                f"{base_url}/commands",
                json={"type": command_type, "issued_by": "flight_launcher_shutdown"},
                timeout=15.0 if command_type == "land" else 8.0,
            )
            print(f"[flight] shutdown {command_type} response: {response.text}", flush=True)
            if command_type == "land":
                try:
                    payload = response.json()
                    land_failed = payload.get("status") != "executed"
                except Exception:
                    land_failed = True
        except KeyboardInterrupt:
            print(f"[flight] shutdown interrupted during {command_type}; continuing cleanup", flush=True)
            if command_type == "land":
                land_failed = True
        except Exception as exc:
            print(f"[flight] shutdown {command_type} failed: {exc}", flush=True)
            if command_type == "land":
                land_failed = True
        try:
            time.sleep(0.25)
        except KeyboardInterrupt:
            print("[flight] shutdown interrupted between commands; continuing cleanup", flush=True)

    if land_failed:
        _post_shutdown_emergency_if_stuck(base_url)


def _post_shutdown_emergency_if_stuck(base_url: str) -> None:
    import httpx

    try:
        health = httpx.get(f"{base_url}/health", timeout=1.5)
        health_payload = health.json() if health.status_code == 200 else {}
    except Exception as exc:
        print(f"[flight] could not read health before emergency fallback: {exc}", flush=True)
        return

    telemetry = health_payload.get("telemetry", {})
    if telemetry.get("flying") is not True:
        print("[flight] land failed, but drone no longer reports flying; skipping emergency", flush=True)
        return

    reasons = _shutdown_emergency_reasons(health_payload)
    if not reasons:
        print("[flight] land failed, but telemetry does not look stuck; skipping emergency", flush=True)
        return

    try:
        response = httpx.post(
            f"{base_url}/commands",
            json={"type": "emergency", "issued_by": "flight_launcher_shutdown"},
            timeout=5.0,
        )
        print(
            f"[flight] shutdown emergency response: {response.text} "
            f"(reasons: {', '.join(reasons)})",
            flush=True,
        )
    except Exception as exc:
        print(f"[flight] shutdown emergency failed: {exc} (reasons: {', '.join(reasons)})", flush=True)


def _shutdown_emergency_reasons(health_payload: dict, *, now: float | None = None) -> list[str]:
    now = time.time() if now is None else now
    telemetry = health_payload.get("telemetry", {})
    raw = telemetry.get("raw") or {}
    video = health_payload.get("video") or {}
    reasons: list[str] = []

    pitch = _float_or_none(raw.get("pitch"))
    roll = _float_or_none(raw.get("roll"))
    if pitch is not None and abs(pitch) >= 35:
        reasons.append(f"pitch={pitch:g}")
    if roll is not None and abs(roll) >= 35:
        reasons.append(f"roll={roll:g}")

    height_cm = _float_or_none(telemetry.get("height_cm"))
    tof = _float_or_none(raw.get("tof"))
    if height_cm is not None and height_cm <= 0 and tof is not None and tof <= 40:
        reasons.append(f"height_cm={height_cm:g} tof={tof:g}")

    latest_sample = video.get("latest_sample") or {}
    latest_ts = _float_or_none(latest_sample.get("timestamp"))
    if latest_ts is not None and now - latest_ts >= 8.0:
        reasons.append(f"stale_video_sample={now - latest_ts:.1f}s")
    elif video.get("running") is True and latest_sample == {}:
        reasons.append("video_running_without_sample")

    return reasons


def _float_or_none(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _post_shutdown_stop_video(base_url: str) -> None:
    import httpx

    try:
        response = httpx.post(f"{base_url}/video/stop", timeout=5.0)
        print(f"[flight] shutdown video stop response: {response.text}", flush=True)
    except KeyboardInterrupt:
        print("[flight] shutdown video stop interrupted; continuing cleanup", flush=True)
    except Exception as exc:
        print(f"[flight] shutdown video stop failed: {exc}", flush=True)


def _stop_flight_processes(procs: Sequence[tuple[str, subprocess.Popen]], base_url: str) -> None:
    non_harness = [(name, proc) for name, proc in procs if name != "harness"]
    harness = [(name, proc) for name, proc in procs if name == "harness"]
    _stop_processes(non_harness)
    if harness and harness[0][1].poll() is None:
        try:
            _post_shutdown_land(base_url)
        except KeyboardInterrupt:
            print("[flight] shutdown landing interrupted; forcing process cleanup", flush=True)
        except Exception as exc:
            print(f"[flight] shutdown landing failed unexpectedly: {exc}", flush=True)
        try:
            _post_shutdown_stop_video(base_url)
        except KeyboardInterrupt:
            print("[flight] shutdown video cleanup interrupted; forcing process cleanup", flush=True)
    _stop_processes(harness)


def build_demo_specs(
    mode: str,
    host: str = "127.0.0.1",
    port: int = 8000,
    fps: float = 5.0,
    video_path: str | None = None,
    log_dir: str = "logs",
    run_id: str | None = None,
    defer_video: bool = False,
) -> list[ProcessSpec]:
    base_url = f"http://{host}:{port}"
    root = _repo_root()
    specs: list[ProcessSpec] = []

    harness_mode = "tello" if mode == "live" else "sim"
    harness = ProcessSpec(
        "harness",
        _harness_argv(harness_mode, host, port, defer_video=mode == "live" and defer_video),
    )
    if not (mode == "live" and defer_video):
        specs.append(harness)

    if mode == "live":
        specs.append(ProcessSpec(
            "rafa",
            [sys.executable, "-m", "breacheye.cli", "rafa",
             "--mode", "models", "--log-dir", log_dir, *_run_id_args(run_id)],
        ))
        specs.append(ProcessSpec(
            "frame_publisher",
            [sys.executable, str(root / "integration" / "frame_publisher.py"),
             "--fps", str(fps), "--harness-url", f"{base_url}/frame/latest",
             "--log-dir", log_dir, *_run_id_args(run_id)],
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
    # post_takeoff=True so run_demo starts it after takeoff completes
    specs.append(ProcessSpec(
        "nav_interpreter",
        [sys.executable, "-m", "breacheye.cli", "nav",
         "--command-url", f"{base_url}/commands", "--log-dir", log_dir, *_run_id_args(run_id)],
        post_takeoff=True,
    ))
    if run_id:
        specs.append(ProcessSpec(
            "map_builder",
            [sys.executable, str(root / "integration" / "map_builder.py"),
             "--log-dir", log_dir, *_run_id_args(run_id)],
            post_takeoff=True,
        ))
    if mode == "live" and defer_video:
        specs.append(harness)

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
    auto_takeoff: bool = True,
    takeoff_climb_cm: int = 100,
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
    _apply_live_safety_defaults(os.environ, mode=resolved_mode, auto_takeoff=auto_takeoff)
    if resolved_mode == "live":
        _apply_local_model_defaults(os.environ, "models")

    defer_video = resolved_mode == "live" and auto_takeoff
    specs = build_demo_specs(
        resolved_mode,
        host,
        port,
        fps,
        video_path,
        log_dir,
        run_id,
        defer_video=defer_video,
    )
    pre_specs = [s for s in specs if not s.post_takeoff]
    post_specs = [s for s in specs if s.post_takeoff]
    procs: list[tuple[str, subprocess.Popen]] = []

    try:
        for spec in pre_specs:
            print(f"[demo] starting {spec.name}", flush=True)
            procs.append((spec.name, subprocess.Popen(spec.argv, env=os.environ.copy(), start_new_session=True)))
            if spec.name == "harness":
                _wait_for_harness(base_url)
            elif spec.name in ("rafa", "playback"):
                time.sleep(0.75)
            elif spec.name == "frame_publisher":
                time.sleep(0.5)

        if resolved_mode == "live" and auto_takeoff:
            _wait_for_takeoff_preflight(base_url, prefix="[demo]")
            _post_takeoff(
                base_url,
                climb_cm=takeoff_climb_cm,
                after_takeoff=lambda: _start_harness_video(base_url, prefix="[demo]"),
            )
            _wait_for_accepts_nav(base_url, prefix="[demo]")

        for spec in post_specs:
            print(f"[demo] starting {spec.name}", flush=True)
            procs.append((spec.name, subprocess.Popen(spec.argv, env=os.environ.copy(), start_new_session=True)))

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
    except Exception as exc:
        print(f"\n[demo] launch failed: {exc}", flush=True)
        return 1
    finally:
        _stop_flight_processes(procs, base_url)


def _resolve_demo_mode(mode: str, video_path: str | None) -> str:
    if mode == "recorded":
        vpath = video_path or str(_repo_root() / "demo" / "sample.mp4")
        if not Path(vpath).exists():
            print(f"[demo] WARNING: video not found ({vpath}) — falling back to mock mode", flush=True)
            mode = "mock"
    return mode


def _wait_for_rafa_navigation(log_dir: str, run_id: str, prefix: str, timeout_s: float = 45.0) -> None:
    path = Path(log_dir).expanduser() / f"{run_id}-rafa.jsonl"
    deadline = time.monotonic() + timeout_s
    print(f"{prefix} waiting for first Rafa navigation decision", flush=True)
    while time.monotonic() < deadline:
        if _rafa_log_has_navigation(path):
            print(f"{prefix} Rafa navigation is warm", flush=True)
            return
        time.sleep(0.25)
    raise RuntimeError(f"Rafa did not publish a navigation decision within {timeout_s:.0f}s; refusing auto-takeoff")


def _rafa_log_has_navigation(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        for line in path.read_text(errors="ignore").splitlines():
            if '"event":"publish"' in line and '"channel":"navigation"' in line:
                return True
    except OSError:
        return False
    return False


def _wait_for_accepts_nav(base_url: str, *, prefix: str, timeout_s: float = 5.0) -> None:
    import httpx

    deadline = time.monotonic() + timeout_s
    last_summary: str | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base_url}/health", timeout=1.0)
            if response.status_code == 200:
                payload = response.json()
                last_summary = _health_summary_from_telemetry(payload.get("telemetry", {}))
                if payload.get("accepts_nav") is True:
                    print(f"{prefix} nav accepted: {last_summary}", flush=True)
                    return
        except Exception:
            pass
        time.sleep(0.25)
    raise RuntimeError(f"autonomous nav did not become enabled after takeoff ({last_summary})")


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


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def _stop_processes(procs: Sequence[tuple[str, subprocess.Popen]]) -> None:
    for name, proc in reversed(procs):
        if proc.poll() is not None:
            continue
        print(f"[flight] stopping {name}", flush=True)
        _signal_process_group(proc, signal.SIGTERM)
    deadline = time.monotonic() + 5.0
    interrupted = False
    for _name, proc in reversed(procs):
        remaining = max(0.1, deadline - time.monotonic())
        try:
            proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            pass
        except KeyboardInterrupt:
            interrupted = True
            break
    for name, proc in reversed(procs):
        if proc.poll() is None:
            if interrupted:
                print(f"[flight] cleanup interrupted; force stopping {name}", flush=True)
            else:
                print(f"[flight] force stopping {name}", flush=True)
            _signal_process_group(proc, signal.SIGKILL)
    kill_deadline = time.monotonic() + 2.0
    for _name, proc in reversed(procs):
        if proc.poll() is not None:
            continue
        try:
            proc.wait(timeout=max(0.1, kill_deadline - time.monotonic()))
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            pass


def _signal_process_group(proc: subprocess.Popen, sig: signal.Signals) -> None:
    try:
        os.killpg(proc.pid, sig)
    except ProcessLookupError:
        return
    except Exception:
        try:
            proc.send_signal(sig)
        except ProcessLookupError:
            return
