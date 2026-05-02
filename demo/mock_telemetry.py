"""Mock telemetry generator — publishes HealthOutput JSON to ZMQ port 5559.

Usage:
    python demo/mock_telemetry.py
    python demo/mock_telemetry.py --frames 200 --fps 1
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time

import zmq

sys.path.insert(0, "src")

from breacheye.rafa.schemas import HealthOutput, MemoryStatus, ModelStatus, Throughput

# Model VRAM baselines (MB)
MODEL_VRAM: dict[str, int] = {
    "moondream": 1800,
    "depth_anything_v2": 600,
    "qwen3_vl": 4200,
}

# Throughput baselines
DETECTION_FPS_RANGE = (10.0, 15.0)
DEPTH_FPS_RANGE = (6.0, 10.0)
DECISION_FPS_RANGE = (0.5, 1.0)

# Memory baselines
RAM_USED_RANGE = (8.0, 9.0)
VRAM_TOTAL_GB = 36.0

# Battery drain: ~0.5% per frame
BATTERY_START = 100.0
BATTERY_DRAIN_PER_FRAME = 0.5
BATTERY_LOW_THRESHOLD = 15.0


def jitter(value: float, pct: float = 0.08) -> float:
    """Apply ±pct fractional jitter to value."""
    return value * (1.0 + random.uniform(-pct, pct))


def generate_frame(frame_id: int, battery_pct: float) -> HealthOutput:
    """Generate one HealthOutput frame."""
    degraded = battery_pct < BATTERY_LOW_THRESHOLD
    pipeline_status = "degraded" if degraded else "ready"

    # VRAM jitter ±2%
    models_loaded = {
        name: ModelStatus(
            status="ready",
            active=name,
            vram_mb=int(jitter(base_vram, 0.02)),
        )
        for name, base_vram in MODEL_VRAM.items()
    }

    detection_fps = round(jitter(random.uniform(*DETECTION_FPS_RANGE)), 2)
    depth_fps = round(jitter(random.uniform(*DEPTH_FPS_RANGE)), 2)
    decision_fps = round(jitter(random.uniform(*DECISION_FPS_RANGE), 0.12), 3)

    throughput = Throughput(
        detection_fps=max(0.0, detection_fps),
        depth_fps=max(0.0, depth_fps),
        decision_fps=max(0.0, decision_fps),
    )

    ram_used_gb = round(jitter(random.uniform(*RAM_USED_RANGE), 0.05), 2)
    memory = MemoryStatus(
        ram_used_gb=ram_used_gb,
        vram_total_gb=VRAM_TOTAL_GB,
    )

    errors: list[str] = []
    if degraded:
        errors.append(f"Low battery: {battery_pct:.1f}%")

    return HealthOutput(
        pipeline_status=pipeline_status,
        models_loaded=models_loaded,
        throughput=throughput,
        memory=memory,
        errors=errors,
        timestamp=time.time(),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish mock HealthOutput to ZMQ port 5559")
    parser.add_argument("--frames", type=int, default=100, help="Number of frames to publish (default: 100)")
    parser.add_argument("--fps", type=float, default=1.0, help="Publish rate in frames per second (default: 1)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    interval = 1.0 / args.fps

    context = zmq.Context()
    socket = context.socket(zmq.PUB)
    socket.bind("tcp://*:5559")

    print(f"[mock_telemetry] Starting — frames={args.frames}, fps={args.fps}")
    print(f"[mock_telemetry] Publishing to tcp://*:5559")
    print(f"[mock_telemetry] Battery drain: {BATTERY_DRAIN_PER_FRAME}%/frame, low threshold: {BATTERY_LOW_THRESHOLD}%")
    time.sleep(0.5)

    battery = BATTERY_START
    try:
        for frame_id in range(args.frames):
            battery = max(0.0, battery - BATTERY_DRAIN_PER_FRAME)
            output = generate_frame(frame_id, battery)
            payload = json.dumps(output.model_dump())
            socket.send_string(payload)

            if frame_id % 10 == 0:
                tp = output.throughput
                mem = output.memory
                print(
                    f"[mock_telemetry] frame={frame_id:03d}  "
                    f"battery={battery:.1f}%  "
                    f"status={output.pipeline_status:<8s}  "
                    f"det_fps={tp.detection_fps:.1f}  "
                    f"ram={mem.ram_used_gb:.1f}GB"
                )

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n[mock_telemetry] Interrupted — shutting down")
    finally:
        socket.close()
        context.term()
        print("[mock_telemetry] Done")


if __name__ == "__main__":
    main()
