from __future__ import annotations

import argparse
import asyncio

import uvicorn
from dotenv import load_dotenv

from breacheye.models import CommandStatus, CommandType, DroneCommand, RCControlPayload
from breacheye.planner import scripted_room_scan
from breacheye.service import HarnessRuntime, create_app


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="breacheye")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Run the local harness API.")
    serve.add_argument("--mode", choices=["sim", "dry_run", "tello"], default="sim")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument(
        "--defer-video",
        action="store_true",
        help="In tello mode, connect the SDK but wait to start streamon/video until /video/start.",
    )
    serve.add_argument(
        "--stabilizer-mode",
        choices=["off", "log", "assist"],
        default=None,
        help="Optional optical-flow hover stabilizer. 'log' records drift only; 'assist' sends tiny corrections.",
    )

    smoke = subparsers.add_parser("smoke", help="Run a conservative connect/takeoff/hover/land sequence.")
    smoke.add_argument("--mode", choices=["sim", "tello"], default="sim")

    offline = subparsers.add_parser("offline", help="Prepare or bundle disconnected run logs.")
    offline.add_argument("offline_command", choices=["preflight", "bundle"])
    offline.add_argument("--log-dir", default="logs")
    offline.add_argument("--run-id")

    html_report = subparsers.add_parser("html-report", help="Build an HTML report for a logged run.")
    html_report.add_argument("--run-id", default="latest", help="Run id to report, or latest.")
    html_report.add_argument("--log-dir", default="logs")
    html_report.add_argument("--output")

    report = subparsers.add_parser("report", help="Fetch and display a post-flight building assessment report.")
    report.add_argument("--run-id", default=None, help="Run ID to fetch (informational; the harness serves its current record).")
    report.add_argument("--format", choices=["text", "json"], default="text", dest="output_format", help="Output format (default: text).")
    report.add_argument("--narrative", action="store_true", help="Include Qwen-generated narrative summary.")
    report.add_argument("--harness-url", default="http://127.0.0.1:8000", help="Base URL of the running harness.")

    monitor = subparsers.add_parser("monitor", help="Watch live harness health, frames, and run logs.")
    monitor.add_argument("--run-id", default="latest", help="Run id to watch, or latest.")
    monitor.add_argument("--log-dir", default="logs")
    monitor.add_argument("--harness-url", default="http://127.0.0.1:8000")
    monitor.add_argument("--interval-s", type=float, default=1.0)
    monitor.add_argument("--frame-interval-s", type=float, default=2.0)
    monitor.add_argument("--duration-s", type=float)
    monitor.add_argument("--no-save-frames", action="store_true")

    rafa = subparsers.add_parser("rafa", help="Run Rafa's local ZMQ VLM pipeline.")
    rafa.add_argument("rafa_command", nargs="?", choices=["run", "doctor"], default="run")
    rafa.add_argument("--mode", choices=["stub", "models", "detector-only"], default="stub")
    rafa.add_argument("--json", action="store_true", help="Print doctor output as JSON.")
    rafa.add_argument("--log-dir", default="logs", help="Directory for JSONL run logs.")
    rafa.add_argument("--run-id", help="Stable run id used in log file names.")
    rafa.add_argument(
        "--require-models",
        action="store_true",
        help="Exit non-zero from doctor unless real model dependencies and weights are ready.",
    )

    nav = subparsers.add_parser("nav", help="Bridge Rafa navigation decisions into the safety harness.")
    nav.add_argument("--endpoint", default="tcp://127.0.0.1:5558")
    nav.add_argument("--command-url", default="http://127.0.0.1:8000/commands")
    nav.add_argument("--log-dir", default="logs")
    nav.add_argument("--run-id")

    fly = subparsers.add_parser("fly", help="Launch the local harness, Rafa pipeline, frame publisher, and nav bridge.")
    fly.add_argument("--mode", choices=["sim", "tello"], default="sim")
    fly.add_argument("--rafa-mode", choices=["stub", "models", "detector-only"], default="stub")
    fly.add_argument("--host", default="127.0.0.1")
    fly.add_argument("--port", type=int, default=8000)
    fly.add_argument("--fps", type=float, default=5.0)
    fly.add_argument("--log-dir", default="logs")
    fly.add_argument("--run-id")
    fly.add_argument("--frame-source", choices=["auto", "synthetic", "harness", "tello"], default="auto")
    fly.add_argument("--auto-takeoff", action="store_true", help="Issue takeoff once the loop is running.")
    fly.add_argument(
        "--takeoff-climb-cm",
        type=int,
        default=100,
        help="Extra climb after auto-takeoff to reduce ground-effect drift. Use 0 to disable.",
    )
    fly.add_argument("--duration-s", type=float, help="Stop the launched loop after this many seconds.")

    calibrate = subparsers.add_parser(
        "calibrate",
        help="Aggressive flight test: 360° rotations, 3ft circles, and a flip.",
    )
    calibrate.add_argument(
        "--harness-url",
        default="http://127.0.0.1:8000",
        help="Base URL of the running harness (default: http://127.0.0.1:8000)",
    )
    calibrate.add_argument(
        "--yaw-speed",
        type=int,
        default=30,
        help="RC yaw value for rotations, 1-100 (default: 30)",
    )
    calibrate.add_argument(
        "--rotation-steps",
        type=int,
        default=12,
        help="Number of steps per full rotation (default: 12)",
    )
    calibrate.add_argument(
        "--circle-speed",
        type=int,
        default=30,
        help="Forward speed during circles, 1-100 (default: 30)",
    )
    calibrate.add_argument(
        "--circle-yaw",
        type=int,
        default=20,
        help="Yaw rate during circles — lower = wider radius (default: 20)",
    )
    calibrate.add_argument(
        "--circle-steps",
        type=int,
        default=18,
        help="Number of steps per full circle (default: 18)",
    )
    calibrate.add_argument(
        "--step-ms",
        type=int,
        default=1000,
        help="Duration of each RC sub-step in ms (default: 1000)",
    )
    calibrate.add_argument(
        "--no-flip",
        action="store_true",
        help="Skip flip maneuver",
    )
    calibrate.add_argument(
        "--takeoff-climb-cm",
        type=int,
        default=60,
        metavar="CM",
        help="Extra climb after takeoff before horizontal tests. Use 0 to disable (default: 60)",
    )
    calibrate.add_argument(
        "--min-battery",
        type=int,
        default=30,
        metavar="PERCENT",
        help="Minimum battery required before and during calibration (default: 30)",
    )
    calibrate.add_argument(
        "--allow-hover-trim",
        action="store_true",
        help="Allow non-neutral harness hover trim during calibration.",
    )
    calibrate.add_argument(
        "--yes",
        action="store_true",
        help="Run without pressing Enter before each action.",
    )
    calibrate.add_argument("--log-dir", default="logs")
    calibrate.add_argument("--run-id")

    demo = subparsers.add_parser("demo", help="Launch live, recorded, or mock demo stack.")
    demo.add_argument("--mode", choices=["live", "recorded", "mock"], default="live",
                      help="Demo mode (default: live)")
    demo.add_argument("--host", default="127.0.0.1")
    demo.add_argument("--port", type=int, default=8000)
    demo.add_argument("--fps", type=float, default=5.0)
    demo.add_argument("--video", help="Video file for recorded mode (default: demo/sample.mp4)")
    demo.add_argument("--log-dir", default="logs")
    demo.add_argument("--run-id")
    demo.add_argument("--duration-s", type=float, help="Stop demo after N seconds.")
    demo.add_argument(
        "--no-auto-takeoff",
        action="store_true",
        help="For live demo mode, start the stack without issuing takeoff.",
    )
    demo.add_argument(
        "--takeoff-climb-cm",
        type=int,
        default=100,
        help="Extra climb after live demo auto-takeoff. Use 0 to disable.",
    )

    args = parser.parse_args()
    if args.command == "serve":
        app = create_app(
            mode=args.mode,
            start_video_on_start=not args.defer_video,
            stabilizer_mode=args.stabilizer_mode,
        )
        uvicorn.run(app, host=args.host, port=args.port)
    elif args.command == "smoke":
        raise SystemExit(asyncio.run(_smoke(args.mode)))
    elif args.command == "offline":
        _offline(args.offline_command, log_dir=args.log_dir, run_id=args.run_id)
    elif args.command == "html-report":
        _report(run_id=args.run_id, log_dir=args.log_dir, output=args.output)
    elif args.command == "report":
        raise SystemExit(
            asyncio.run(
                _building_report(
                    harness_url=args.harness_url,
                    output_format=args.output_format,
                    narrative=args.narrative,
                )
            )
        )
    elif args.command == "monitor":
        raise SystemExit(
            _monitor(
                run_id=args.run_id,
                log_dir=args.log_dir,
                harness_url=args.harness_url,
                interval_s=args.interval_s,
                frame_interval_s=args.frame_interval_s,
                duration_s=args.duration_s,
                save_frames=not args.no_save_frames,
            )
        )
    elif args.command == "rafa":
        if args.rafa_command == "doctor":
            _rafa_doctor(json_output=args.json, require_models=args.require_models)
        else:
            asyncio.run(_rafa(args.mode, log_dir=args.log_dir, run_id=args.run_id))
    elif args.command == "nav":
        asyncio.run(_nav(endpoint=args.endpoint, command_url=args.command_url, log_dir=args.log_dir, run_id=args.run_id))
    elif args.command == "fly":
        raise SystemExit(
            _fly(
                mode=args.mode,
                rafa_mode=args.rafa_mode,
                host=args.host,
                port=args.port,
                fps=args.fps,
                log_dir=args.log_dir,
                run_id=args.run_id,
                frame_source=args.frame_source,
                auto_takeoff=args.auto_takeoff,
                takeoff_climb_cm=args.takeoff_climb_cm,
                duration_s=args.duration_s,
            )
        )
    elif args.command == "calibrate":
        from breacheye.calibration import CalibConfig, run_calibration

        cfg = CalibConfig(
            yaw_speed=args.yaw_speed,
            rotation_steps=args.rotation_steps,
            circle_forward=args.circle_speed,
            circle_yaw=args.circle_yaw,
            circle_steps=args.circle_steps,
            step_duration_ms=args.step_ms,
            enable_flip=not args.no_flip,
            takeoff_climb_cm=args.takeoff_climb_cm,
            min_battery=args.min_battery,
            allow_hover_trim=args.allow_hover_trim,
            confirm_each=not args.yes,
        )
        raise SystemExit(
            run_calibration(
                base_url=args.harness_url,
                cfg=cfg,
                log_dir=args.log_dir,
                run_id=args.run_id,
            )
        )
    elif args.command == "demo":
        raise SystemExit(_demo(
            mode=args.mode,
            host=args.host,
            port=args.port,
            fps=args.fps,
            video=args.video,
            log_dir=args.log_dir,
            run_id=args.run_id,
            duration_s=args.duration_s,
            auto_takeoff=not args.no_auto_takeoff,
            takeoff_climb_cm=args.takeoff_climb_cm,
        ))


async def _smoke(mode: str) -> int:
    runtime = HarnessRuntime(mode, start_video_on_start=mode != "tello")
    await runtime.start()
    try:
        telemetry = await runtime.safety.telemetry()
        print({"event": "preflight_telemetry", "telemetry": telemetry.model_dump()})

        takeoff = DroneCommand(type=CommandType.TAKEOFF, issued_by="smoke")
        result = await runtime.safety.execute(takeoff)
        print(result.model_dump())
        if result.status != CommandStatus.EXECUTED:
            telemetry = await runtime.safety.telemetry()
            print({"event": "takeoff_failed_telemetry", "telemetry": telemetry.model_dump()})
            return 1
        if mode == "tello":
            await runtime.start_video()

        for command in [
            DroneCommand(
                type=CommandType.RC_CONTROL,
                issued_by="smoke",
                ttl_ms=500,
                payload=RCControlPayload(yaw=20, duration_ms=300),
            ),
            *scripted_room_scan(issued_by="smoke"),
            DroneCommand(type=CommandType.LAND, issued_by="smoke"),
        ]:
            result = await runtime.safety.execute(command)
            print(result.model_dump())
            if result.status != CommandStatus.EXECUTED:
                telemetry = await runtime.safety.telemetry()
                print({"event": "command_failed_telemetry", "telemetry": telemetry.model_dump()})
                return 1
        return 0
    finally:
        await runtime.stop()


async def _rafa(mode: str, log_dir: str | None = "logs", run_id: str | None = None) -> None:
    from breacheye.rafa import RafaPipeline, RafaPipelineConfig

    pipeline = RafaPipeline(RafaPipelineConfig(mode=mode, log_dir=log_dir, run_id=run_id))
    await pipeline.run_forever()


async def _nav(endpoint: str, command_url: str, log_dir: str | None = "logs", run_id: str | None = None) -> None:
    from breacheye.nav_interpreter import NavInterpreter

    interpreter = NavInterpreter(endpoint=endpoint, command_url=command_url, log_dir=log_dir, run_id=run_id)
    interpreter.start()
    try:
        await interpreter.run_forever()
    finally:
        await interpreter.aclose()


def _fly(
    *,
    mode: str,
    rafa_mode: str,
    host: str,
    port: int,
    fps: float,
    log_dir: str,
    run_id: str | None,
    frame_source: str,
    auto_takeoff: bool,
    takeoff_climb_cm: int,
    duration_s: float | None,
) -> int:
    from breacheye.flight import FlightLaunchConfig, run_flight

    return run_flight(
        FlightLaunchConfig(
            mode=mode,
            rafa_mode=rafa_mode,
            host=host,
            port=port,
            fps=fps,
            log_dir=log_dir,
            run_id=run_id,
            frame_source=frame_source,
            auto_takeoff=auto_takeoff,
            takeoff_climb_cm=takeoff_climb_cm,
            duration_s=duration_s,
        )
    )


def _demo(
    *,
    mode: str,
    host: str,
    port: int,
    fps: float,
    video: str | None,
    log_dir: str,
    run_id: str | None,
    duration_s: float | None,
    auto_takeoff: bool,
    takeoff_climb_cm: int,
) -> int:
    from breacheye.flight import run_demo

    return run_demo(
        mode=mode,
        host=host,
        port=port,
        fps=fps,
        video_path=video,
        log_dir=log_dir,
        run_id=run_id,
        duration_s=duration_s,
        auto_takeoff=auto_takeoff,
        takeoff_climb_cm=takeoff_climb_cm,
    )


def _rafa_doctor(json_output: bool = False, require_models: bool = False) -> None:
    from breacheye.rafa.readiness import check_rafa_readiness

    readiness = check_rafa_readiness()
    print(readiness.to_json() if json_output else readiness.to_text())
    if not readiness.stub_ready or (require_models and not readiness.models_ready):
        raise SystemExit(1)


def _offline(command: str, log_dir: str = "logs", run_id: str | None = None) -> None:
    from breacheye.offline import create_bundle, write_preflight

    if command == "preflight":
        path = write_preflight(log_dir=log_dir, run_id=run_id)
    else:
        path = create_bundle(log_dir=log_dir, run_id=run_id)
    print(path)


async def _building_report(
    *,
    harness_url: str,
    output_format: str,
    narrative: bool,
) -> int:
    """Fetch a BuildingReport from the harness and display it."""
    import json as _json
    import urllib.request
    import urllib.error

    from breacheye.report import BuildingReport
    from breacheye.report_generator import ReportGenerator

    url = harness_url.rstrip("/") + "/report"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = _json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        print(f"error: could not reach harness at {url}: {exc}", flush=True)
        return 1

    try:
        report = BuildingReport.model_validate(data)
    except Exception as exc:
        print(f"error: invalid report payload from harness: {exc}", flush=True)
        return 1

    generator = ReportGenerator()

    if narrative:
        report.narrative = await generator.generate_narrative(report)

    if output_format == "json":
        print(report.model_dump_json(indent=2))
    else:
        print(generator.generate_text_report(report))

    return 0


def _report(run_id: str, log_dir: str = "logs", output: str | None = None) -> None:
    from pathlib import Path

    from ai.run_report import build_report
    from breacheye.monitor import resolve_run_id

    resolved = resolve_run_id(Path(log_dir).expanduser(), run_id)
    if resolved is None:
        raise SystemExit(f"no run logs found in {log_dir!r}")
    path = build_report(Path(log_dir).expanduser(), resolved, Path(output) if output else None)
    print(path)


def _monitor(
    *,
    run_id: str,
    log_dir: str,
    harness_url: str,
    interval_s: float,
    frame_interval_s: float,
    duration_s: float | None,
    save_frames: bool,
) -> int:
    from breacheye.monitor import monitor_run

    return monitor_run(
        log_dir=log_dir,
        run_id=run_id,
        harness_url=harness_url,
        interval_s=interval_s,
        frame_interval_s=frame_interval_s,
        duration_s=duration_s,
        save_frames=save_frames,
    )


if __name__ == "__main__":
    main()
