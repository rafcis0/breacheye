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
    rafa.add_argument("--mode", choices=["stub", "models", "detector-only"], default="stub")

    args = parser.parse_args()
    if args.command == "serve":
        app = create_app(mode=args.mode)
        uvicorn.run(app, host=args.host, port=args.port)
    elif args.command == "smoke":
        asyncio.run(_smoke(args.mode))
    elif args.command == "rafa":
        asyncio.run(_rafa(args.mode))


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


async def _rafa(mode: str) -> None:
    from breacheye.rafa import RafaPipeline, RafaPipelineConfig

    pipeline = RafaPipeline(RafaPipelineConfig(mode=mode))
    await pipeline.run_forever()


if __name__ == "__main__":
    main()
