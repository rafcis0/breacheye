"""Mock detection generator — publishes DetectionOutput JSON to ZMQ port 5556.

Usage:
    python demo/mock_detections.py
    python demo/mock_detections.py --frames 50 --poi-density 5 --fps 5
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time

import zmq

# Ensure the package is importable when run from repo root
sys.path.insert(0, "src")

from breacheye.rafa.schemas import BBox2D, Detection, DetectionOutput

# Frame dimensions
FRAME_W = 960
FRAME_H = 720

POI_LABEL_MAP: dict[str, str] = {
    "T1-01": "Entry/Exit Point",
    "T1-02": "Fatal Funnel",
    "T1-03": "Stairs/Vertical",
    "T2-02": "Threat Indicator",
    "T2-03": "Chokepoint",
    "T3-01": "Utility Panel",
    "T4-01": "Structural Damage",
    "ROOM": "Room/Open Area",
}

# Threat levels weighted toward lower severity for realism
THREAT_WEIGHTS = {
    "HOT": 0.05,
    "WARM": 0.15,
    "CAUTION": 0.30,
    "CLEAR": 0.35,
    "INFO": 0.15,
}

CATEGORIES = list(POI_LABEL_MAP.keys())
THREAT_LEVELS = list(THREAT_WEIGHTS.keys())
THREAT_PROBS = list(THREAT_WEIGHTS.values())

# Description templates per category
DESCRIPTIONS: dict[str, list[str]] = {
    "T1-01": ["Door frame visible", "Opening detected", "Threshold identified"],
    "T1-02": ["Narrow passage ahead", "Funnel geometry detected", "High-exposure corridor"],
    "T1-03": ["Staircase structure", "Vertical transition point", "Elevation change"],
    "T2-02": ["Potential hostile indicator", "Anomalous object", "Threat marker"],
    "T2-03": ["Bottleneck geometry", "Single file passage", "Tactical chokepoint"],
    "T3-01": ["Electrical panel", "Utility access point", "Infrastructure node"],
    "T4-01": ["Structural compromise", "Debris field", "Wall breach"],
    "ROOM": ["Open area cleared", "Room boundary detected", "Space mapped"],
}


def random_bbox() -> BBox2D:
    """Generate a random plausible bounding box within 960x720."""
    # Minimum size 40px, maximum 300px per dimension
    w = random.randint(40, 300)
    h = random.randint(40, 250)
    x1 = random.randint(0, FRAME_W - w - 1)
    y1 = random.randint(0, FRAME_H - h - 1)
    return BBox2D(x1=x1, y1=y1, x2=x1 + w, y2=y1 + h)


def generate_frame(frame_id: int, max_detections: int) -> DetectionOutput:
    """Generate one DetectionOutput with 0..max_detections detections."""
    # ~20% of frames have zero detections
    n = 0 if random.random() < 0.20 else random.randint(1, max_detections)

    detections: list[Detection] = []
    for idx in range(n):
        category = random.choice(CATEGORIES)
        threat_level = random.choices(THREAT_LEVELS, weights=THREAT_PROBS, k=1)[0]
        confidence = round(random.uniform(0.40, 0.95), 3)
        description = random.choice(DESCRIPTIONS[category])

        det = Detection(
            id=f"det-{frame_id:03d}-{idx:03d}",
            category=category,
            label=POI_LABEL_MAP[category],
            description=description,
            confidence=confidence,
            bbox_2d=random_bbox(),
            threat_level=threat_level,
            detection_model="moondream",
        )
        detections.append(det)

    processing_ms = random.randint(15, 35)
    return DetectionOutput(
        frame_id=frame_id,
        timestamp=time.time(),
        detections=detections,
        processing_ms=processing_ms,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish mock DetectionOutput to ZMQ port 5556")
    parser.add_argument("--frames", type=int, default=100, help="Number of frames to publish (default: 100)")
    parser.add_argument("--poi-density", type=int, default=3, help="Max detections per frame (default: 3)")
    parser.add_argument("--fps", type=float, default=10.0, help="Publish rate in frames per second (default: 10)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    interval = 1.0 / args.fps

    context = zmq.Context()
    socket = context.socket(zmq.PUB)
    socket.bind("tcp://*:5556")

    print(f"[mock_detections] Starting — frames={args.frames}, poi_density={args.poi_density}, fps={args.fps}")
    print(f"[mock_detections] Publishing to tcp://*:5556")
    # Brief sleep so subscribers can connect before first message
    time.sleep(0.5)

    try:
        for frame_id in range(args.frames):
            output = generate_frame(frame_id, args.poi_density)
            payload = json.dumps(output.model_dump())
            socket.send_string(payload)

            if frame_id % 10 == 0:
                det_count = len(output.detections)
                print(f"[mock_detections] frame={frame_id:03d}  detections={det_count}")

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n[mock_detections] Interrupted — shutting down")
    finally:
        socket.close()
        context.term()
        print("[mock_detections] Done")


if __name__ == "__main__":
    main()
