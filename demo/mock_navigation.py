"""Mock navigation generator — publishes NavigationOutput JSON to ZMQ port 5558.

Usage:
    python demo/mock_navigation.py
    python demo/mock_navigation.py --frames 50 --pattern corridor_follow --fps 2
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time

import zmq

sys.path.insert(0, "src")

from breacheye.rafa.schemas import NavigationDecision, NavigationOutput

# ── Pattern definitions ──────────────────────────────────────────────────────

# room_sweep: systematic rotation then forward movement
ROOM_SWEEP_CYCLE = [
    "rotate_right",
    "rotate_right",
    "rotate_right",
    "rotate_right",
    "move_forward",
    "move_forward",
    "rotate_left",
    "rotate_left",
    "rotate_left",
    "rotate_left",
    "move_forward",
    "hover",
]

# corridor_follow: mostly forward with occasional turns
CORRIDOR_FOLLOW_WEIGHTS = {
    "move_forward": 0.55,
    "rotate_left": 0.10,
    "rotate_right": 0.10,
    "move_up": 0.05,
    "move_down": 0.05,
    "hover": 0.10,
    "move_back": 0.05,
}

# random_explore: uniform over all actions except land
RANDOM_ACTIONS = [
    "move_forward",
    "move_back",
    "move_left",
    "move_right",
    "move_up",
    "move_down",
    "rotate_left",
    "rotate_right",
    "hover",
]

REASONING_MAP: dict[str, list[str]] = {
    "move_forward": [
        "Clear path ahead — advancing",
        "No obstacles detected — continuing forward",
        "Open corridor — pushing forward",
    ],
    "move_back": [
        "Backing away from obstacle",
        "Retreating to improve angle",
        "Collision risk — reversing",
    ],
    "move_left": [
        "Sweeping left quadrant",
        "Lateral shift for coverage",
        "Avoiding detected obstacle on right",
    ],
    "move_right": [
        "Sweeping right quadrant",
        "Lateral shift for coverage",
        "Avoiding detected obstacle on left",
    ],
    "move_up": [
        "Gaining altitude for overview",
        "Clearing ground-level obstruction",
        "Ascending to map upper zone",
    ],
    "move_down": [
        "Descending for detail capture",
        "Lowering altitude to inspect POI",
        "Reducing elevation for passage",
    ],
    "rotate_left": [
        "Scanning left sector",
        "Turning to investigate left flank",
        "Coverage sweep — rotating left",
    ],
    "rotate_right": [
        "Scanning right sector",
        "Turning to investigate right flank",
        "Coverage sweep — rotating right",
    ],
    "hover": [
        "Holding position for analysis",
        "Stationary capture for keyframe",
        "Pausing — processing detections",
    ],
    "land": [
        "Mission complete — landing",
        "Low battery — initiating landing",
    ],
}

# Exploration state progression weights (transitions are frame-by-frame probabilistic)
# Format: {current_state: {next_state: probability}}
STATE_TRANSITIONS: dict[str, dict[str, float]] = {
    "exploring": {
        "exploring": 0.75,
        "investigating_poi": 0.15,
        "obstacle_avoidance": 0.07,
        "coverage_complete": 0.03,
    },
    "investigating_poi": {
        "investigating_poi": 0.50,
        "exploring": 0.40,
        "obstacle_avoidance": 0.10,
    },
    "obstacle_avoidance": {
        "obstacle_avoidance": 0.40,
        "exploring": 0.55,
        "returning": 0.05,
    },
    "coverage_complete": {
        "coverage_complete": 0.70,
        "returning": 0.30,
    },
    "returning": {
        "returning": 0.80,
        "exploring": 0.20,
    },
    "low_battery": {
        "low_battery": 0.90,
        "returning": 0.10,
    },
}


def next_state(current: str, frame_id: int, total_frames: int) -> str:
    """Transition exploration state probabilistically; force low_battery near end."""
    # Force low_battery in the last 10% of frames
    if frame_id >= int(total_frames * 0.90) and current not in ("low_battery", "returning"):
        return "low_battery"

    transitions = STATE_TRANSITIONS.get(current, {"exploring": 1.0})
    states = list(transitions.keys())
    probs = list(transitions.values())
    return random.choices(states, weights=probs, k=1)[0]


def room_sweep_action(frame_id: int) -> str:
    return ROOM_SWEEP_CYCLE[frame_id % len(ROOM_SWEEP_CYCLE)]


def corridor_follow_action() -> str:
    actions = list(CORRIDOR_FOLLOW_WEIGHTS.keys())
    weights = list(CORRIDOR_FOLLOW_WEIGHTS.values())
    return random.choices(actions, weights=weights, k=1)[0]


def random_explore_action() -> str:
    return random.choice(RANDOM_ACTIONS)


def generate_frame(
    frame_id: int,
    pattern: str,
    total_frames: int,
    current_state: str,
) -> tuple[NavigationOutput, str]:
    """Return (NavigationOutput, new_exploration_state)."""
    if pattern == "room_sweep":
        action = room_sweep_action(frame_id)
    elif pattern == "corridor_follow":
        action = corridor_follow_action()
    else:
        action = random_explore_action()

    # State may be overridden to match action context
    exp_state = next_state(current_state, frame_id, total_frames)

    # If in low_battery or returning, prefer hover/back actions
    if exp_state in ("low_battery", "returning") and pattern != "room_sweep":
        action = random.choices(
            ["hover", "move_back", "rotate_left", "rotate_right"],
            weights=[0.50, 0.30, 0.10, 0.10],
            k=1,
        )[0]

    confidence = round(random.uniform(0.30, 0.95), 3)
    reasoning = random.choice(REASONING_MAP.get(action, ["Executing action"]))

    decision = NavigationDecision(
        action=action,
        params={},
        confidence=confidence,
        reasoning=reasoning,
        exploration_state=exp_state,
    )
    output = NavigationOutput(
        frame_id=frame_id,
        timestamp=time.time(),
        decision=decision,
    )
    return output, exp_state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish mock NavigationOutput to ZMQ port 5558")
    parser.add_argument("--frames", type=int, default=100, help="Number of frames to publish (default: 100)")
    parser.add_argument(
        "--pattern",
        choices=["room_sweep", "corridor_follow", "random_explore"],
        default="room_sweep",
        help="Navigation pattern to simulate (default: room_sweep)",
    )
    parser.add_argument("--fps", type=float, default=2.0, help="Publish rate in frames per second (default: 2)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    interval = 1.0 / args.fps

    context = zmq.Context()
    socket = context.socket(zmq.PUB)
    socket.bind("tcp://*:5558")

    print(f"[mock_navigation] Starting — frames={args.frames}, pattern={args.pattern}, fps={args.fps}")
    print(f"[mock_navigation] Publishing to tcp://*:5558")
    time.sleep(0.5)

    current_state = "exploring"
    try:
        for frame_id in range(args.frames):
            output, current_state = generate_frame(frame_id, args.pattern, args.frames, current_state)
            payload = json.dumps(output.model_dump())
            socket.send_string(payload)

            if frame_id % 10 == 0:
                d = output.decision
                print(
                    f"[mock_navigation] frame={frame_id:03d}  "
                    f"action={d.action:<16s}  state={d.exploration_state:<20s}  conf={d.confidence:.2f}"
                )

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n[mock_navigation] Interrupted — shutting down")
    finally:
        socket.close()
        context.term()
        print("[mock_navigation] Done")


if __name__ == "__main__":
    main()
