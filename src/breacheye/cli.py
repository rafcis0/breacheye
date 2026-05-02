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

    args = parser.parse_args()
    if args.command == "serve":
        app = create_app(mode=args.mode)
        uvicorn.run(app, host=args.host, port=args.port)
    elif args.command == "smoke":
        asyncio.run(_smoke(args.mode))
    elif args.command == "rafa":
        if args.rafa_command == "doctor":
            _rafa_doctor(json_output=args.json, require_models=args.require_models)
        else:
            asyncio.run(_rafa(args.mode, log_dir=args.log_dir, run_id=args.run_id))


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


def _rafa_doctor(json_output: bool = False, require_models: bool = False) -> None:
    from breacheye.rafa.readiness import check_rafa_readiness

    readiness = check_rafa_readiness()
    print(readiness.to_json() if json_output else readiness.to_text())
    if not readiness.stub_ready or (require_models and not readiness.models_ready):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
