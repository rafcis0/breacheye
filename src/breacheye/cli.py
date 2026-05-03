from __future__ import annotations

import argparse
import asyncio

import uvicorn

from breacheye.models import CommandType, DroneCommand, RCControlPayload
from breacheye.planner import scripted_room_scan
from breacheye.service import HarnessRuntime, create_app


def main() -> None:
    parser = argparse.ArgumentParser(prog="breacheye")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Run the local harness API.")
    serve.add_argument("--mode", choices=["sim", "dry_run", "tello"], default="sim")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    smoke = subparsers.add_parser("smoke", help="Run a conservative connect/takeoff/hover/land sequence.")
    smoke.add_argument("--mode", choices=["sim", "tello"], default="sim")

    offline = subparsers.add_parser("offline", help="Prepare or bundle disconnected run logs.")
    offline.add_argument("offline_command", choices=["preflight", "bundle"])
    offline.add_argument("--log-dir", default="logs")
    offline.add_argument("--run-id")

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

    demo = subparsers.add_parser("demo", help="Launch demo with auto-fallback (live -> recorded -> mock).")
    demo.add_argument("--mode", choices=["live", "recorded", "mock"], default="live",
                      help="Demo mode (default: live, auto-degrades if needed)")
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
        app = create_app(mode=args.mode)
        uvicorn.run(app, host=args.host, port=args.port)
    elif args.command == "smoke":
        asyncio.run(_smoke(args.mode))
    elif args.command == "offline":
        _offline(args.offline_command, log_dir=args.log_dir, run_id=args.run_id)
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


async def _smoke(mode: str) -> None:
    runtime = HarnessRuntime(mode)
    await runtime.start()
    try:
        for command in [
            DroneCommand(type=CommandType.TAKEOFF, issued_by="smoke"),
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


if __name__ == "__main__":
    main()
