"""Live hardware calibration tool for BreachEye.

Verifies that each NavigationAction the VLM models produce translates to the
correct physical drone movement.  The operator watches the drone and confirms
each action matches expectations.

Usage (harness must already be running via `breacheye serve --mode tello`):

    python -m breacheye.calibration
    breacheye calibrate

Optional flags:
    --harness-url   Base URL of the running harness  (default: http://127.0.0.1:8000)
    --observe-s     Seconds to hold after each command for visual confirmation (default: 3)
    --speed         Movement speed in cm/s, 1-35  (default: 25)
    --distance-cm   Translation distance in cm     (default: 35)
    --degrees       Rotation angle in degrees      (default: 45)
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import NamedTuple

import httpx

from breacheye.models import CommandType, DroneCommand, RCControlPayload


# ---------------------------------------------------------------------------
# Action sequence
# ---------------------------------------------------------------------------

class _Step(NamedTuple):
    action: str
    label: str
    expect: str


_SEQUENCE: list[_Step] = [
    _Step("hover",        "hover",        "drone holds position"),
    _Step("move_forward", "move_forward",  "drone moves forward ~35 cm"),
    _Step("hover",        "hover",        "drone stabilises"),
    _Step("move_back",    "move_back",    "drone moves backward ~35 cm"),
    _Step("hover",        "hover",        "drone stabilises"),
    _Step("move_left",    "move_left",    "drone strafes left ~35 cm"),
    _Step("hover",        "hover",        "drone stabilises"),
    _Step("move_right",   "move_right",   "drone strafes right ~35 cm"),
    _Step("hover",        "hover",        "drone stabilises"),
    _Step("move_up",      "move_up",      "drone gains altitude ~35 cm"),
    _Step("hover",        "hover",        "drone stabilises"),
    _Step("move_down",    "move_down",    "drone loses altitude ~35 cm"),
    _Step("hover",        "hover",        "drone stabilises"),
    _Step("rotate_left",  "rotate_left",  "drone yaws left ~45 degrees"),
    _Step("hover",        "hover",        "drone stabilises"),
    _Step("rotate_right", "rotate_right", "drone yaws right ~45 degrees"),
    _Step("hover",        "hover",        "drone stabilises"),
    _Step("land",         "land",         "drone lands"),
]


# ---------------------------------------------------------------------------
# Command builders — mirrors NavInterpreter._map_action exactly
# ---------------------------------------------------------------------------

@dataclass
class CalibConfig:
    speed: int = 25        # cm/s, clamped to SafetyController max (35)
    distance_cm: int = 35  # translation distance
    degrees: int = 45      # rotation angle
    max_move_duration_ms: int = 1000
    max_yaw_duration_ms: int = 1000


def _build_command(action: str, cfg: CalibConfig) -> DroneCommand:
    """Mirror of NavInterpreter._map_action with calibration-friendly params."""

    if action == "hover":
        return DroneCommand(type=CommandType.HOVER, issued_by="calibration")

    if action == "land":
        return DroneCommand(type=CommandType.LAND, issued_by="calibration")

    speed = max(1, min(100, cfg.speed))

    if action in ("move_up", "move_down"):
        distance = cfg.distance_cm
    else:
        distance = cfg.distance_cm

    if action in ("rotate_left", "rotate_right"):
        duration_ms = max(100, min(cfg.max_yaw_duration_ms,
                                   int(cfg.degrees / 90 * 1000)))
    else:
        duration_ms = max(100, min(cfg.max_move_duration_ms,
                                   int(distance / max(speed, 1) * 1000)))

    ttl_ms = min(1200, duration_ms + 200)

    vel_map = {
        "move_forward": {"forward_back": speed},
        "move_back":    {"forward_back": -speed},
        "move_left":    {"left_right":   -speed},
        "move_right":   {"left_right":    speed},
        "move_up":      {"up_down":       speed},
        "move_down":    {"up_down":      -speed},
        "rotate_left":  {"yaw": -25},
        "rotate_right": {"yaw":  25},
    }

    axes = vel_map[action]
    payload = RCControlPayload(duration_ms=duration_ms, **axes)

    return DroneCommand(
        type=CommandType.RC_CONTROL,
        issued_by="calibration",
        ttl_ms=ttl_ms,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _health_check(client: httpx.Client, base_url: str) -> dict:
    try:
        resp = client.get(f"{base_url}/health", timeout=5.0)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        _abort(f"harness unreachable at {base_url}/health: {exc}")


def _post_command(
    client: httpx.Client,
    base_url: str,
    cmd: DroneCommand,
) -> tuple[bool, str]:
    """POST a DroneCommand.  Returns (ok, reason)."""
    try:
        resp = client.post(
            f"{base_url}/commands",
            json=cmd.model_dump(mode="json"),
            timeout=15.0,
        )
    except Exception as exc:
        return False, f"HTTP error: {exc}"

    if resp.status_code != 200:
        return False, f"HTTP {resp.status_code}"

    try:
        body = resp.json()
        status = body.get("status", "?")
        reason = body.get("reason") or ""
        if status == "executed":
            return True, ""
        return False, f"status={status} reason={reason}"
    except Exception:
        return False, "could not parse response body"


def _abort(msg: str) -> None:
    _print_error(f"ABORT: {msg}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Console helpers
# ---------------------------------------------------------------------------

_SEP = "=" * 64


def _print_header(text: str) -> None:
    print(f"\n{_SEP}")
    print(f"  {text}")
    print(_SEP)


def _print_step(idx: int, total: int, action: str, expect: str) -> None:
    print(f"\n[TEST {idx:02d}/{total:02d}] Executing: {action}")
    print(f"           Expecting: {expect}")


def _print_ok(action: str) -> None:
    print(f"[TEST] Done:   {action}  -- did the drone {_verb(action)}? [observe above]")


def _print_fail(action: str, reason: str) -> None:
    print(f"[FAIL] {action}: {reason}")


def _print_error(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)


def _verb(action: str) -> str:
    verbs = {
        "hover":        "hold position",
        "move_forward": "move forward",
        "move_back":    "move backward",
        "move_left":    "strafe left",
        "move_right":   "strafe right",
        "move_up":      "gain altitude",
        "move_down":    "lose altitude",
        "rotate_left":  "yaw left",
        "rotate_right": "yaw right",
        "land":         "land",
    }
    return verbs.get(action, action)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _print_summary(results: list[tuple[str, bool, str]]) -> None:
    _print_header("CALIBRATION CHECKLIST — mark each action you observed")
    passed = 0
    failed = 0
    for action, ok, reason in results:
        if action in ("hover", "land"):
            tag = "[PASS]" if ok else "[FAIL]"
        else:
            tag = "[    ]"  # operator fills in
        line = f"  {tag}  {action:<16}"
        if not ok:
            line += f"  <-- COMMAND FAILED: {reason}"
            failed += 1
        else:
            passed += 1
        print(line)

    print()
    print(f"  Commands sent successfully: {passed}/{len(results)}")
    if failed:
        print(f"  Commands that failed:       {failed}/{len(results)}")
    print()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_calibration(
    base_url: str = "http://127.0.0.1:8000",
    observe_s: float = 3.0,
    cfg: CalibConfig | None = None,
) -> int:
    """Run the full calibration sequence.  Returns 0 on success, 1 on abort."""
    if cfg is None:
        cfg = CalibConfig()

    client = httpx.Client()

    # --- Health check ---
    _print_header("BreachEye Action Calibration")
    print("Checking harness health...")
    health = _health_check(client, base_url)

    mode = health.get("mode", "unknown")
    telemetry = health.get("telemetry", {})
    connected = telemetry.get("connected", False)
    flying = telemetry.get("flying", False)
    battery = telemetry.get("battery")

    print(f"  mode:      {mode}")
    print(f"  connected: {connected}")
    print(f"  flying:    {flying}")
    print(f"  battery:   {battery}%")

    if not connected:
        _abort("drone is not connected — start the harness in tello mode first")

    if mode != "tello":
        print(f"\n[WARN] harness is in '{mode}' mode, not 'tello'. Commands will run but no physical motion will occur.")

    # --- Takeoff ---
    _print_header("TAKEOFF")
    print("Sending takeoff command...")
    takeoff_cmd = DroneCommand(type=CommandType.TAKEOFF, issued_by="calibration")
    ok, reason = _post_command(client, base_url, takeoff_cmd)
    if not ok:
        _abort(f"takeoff failed: {reason}")
    print("Takeoff executed. Hovering 3 seconds to stabilise...")
    time.sleep(3.0)

    # --- Action sequence ---
    results: list[tuple[str, bool, str]] = []
    sequence = _SEQUENCE
    total = len(sequence)

    for idx, step in enumerate(sequence, start=1):
        _print_step(idx, total, step.label, step.expect)

        cmd = _build_command(step.action, cfg)
        ok, reason = _post_command(client, base_url, cmd)

        if ok:
            _print_ok(step.label)
            results.append((step.action, True, ""))
        else:
            _print_fail(step.label, reason)
            results.append((step.action, False, reason))

        if step.action == "land":
            # Final land — no observe delay needed
            break

        time.sleep(observe_s)

    # --- Summary ---
    _print_summary(results)

    failed_count = sum(1 for _, ok, _ in results if not ok)
    return 1 if failed_count else 0


def _parse_args(argv: list[str] | None = None):
    import argparse

    parser = argparse.ArgumentParser(
        prog="breacheye calibrate",
        description="Live hardware calibration: fly each NavigationAction and verify physical motion.",
    )
    parser.add_argument(
        "--harness-url",
        default="http://127.0.0.1:8000",
        help="Base URL of the running harness (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--observe-s",
        type=float,
        default=3.0,
        metavar="SECONDS",
        help="Seconds to pause after each command for visual observation (default: 3)",
    )
    parser.add_argument(
        "--speed",
        type=int,
        default=25,
        metavar="CM_S",
        help="Movement speed in cm/s, 1-35 (default: 25)",
    )
    parser.add_argument(
        "--distance-cm",
        type=int,
        default=35,
        metavar="CM",
        help="Translation distance in cm (default: 35)",
    )
    parser.add_argument(
        "--degrees",
        type=int,
        default=45,
        metavar="DEG",
        help="Rotation angle in degrees (default: 45)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    cfg = CalibConfig(
        speed=args.speed,
        distance_cm=args.distance_cm,
        degrees=args.degrees,
    )
    exit_code = run_calibration(
        base_url=args.harness_url,
        observe_s=args.observe_s,
        cfg=cfg,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
