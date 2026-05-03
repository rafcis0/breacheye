"""Live hardware calibration tool for BreachEye — aggressive flight test.

Runs a continuous maneuver sequence with no pauses:
  - Full 360° rotation left and right (sequential RC yaw commands)
  - 3ft radius circle left and right (forward + yaw RC commands)
  - Forward flip (if enabled and battery >= 50%)

Operator controls (active during flight):
  SPACE       — emergency landing (graceful)
  SPACE×2     — kill motors (immediate)

Usage (harness must already be running via `breacheye serve --mode tello`):

    breacheye calibrate
    breacheye calibrate --yaw-speed 35 --no-flip
"""
from __future__ import annotations

import select
import sys
import termios
import threading
import tty
from dataclasses import dataclass
from time import sleep

import httpx

from breacheye.models import CommandType, DroneCommand, FlipPayload, RCControlPayload


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class CalibConfig:
    yaw_speed: int = 30           # RC yaw value for rotations
    rotation_steps: int = 12      # steps per full rotation (~12s at yaw=30)
    circle_forward: int = 30      # forward speed during circles
    circle_yaw: int = 20          # yaw rate during circles (lower = wider radius)
    circle_steps: int = 18        # steps per full circle (~18s)
    step_duration_ms: int = 1000  # duration of each RC sub-step
    enable_flip: bool = True      # attempt flip if battery allows
    takeoff_climb_cm: int = 60
    min_battery: int = 30
    allow_hover_trim: bool = False
    confirm_each: bool = True


# ---------------------------------------------------------------------------
# Keyboard monitor — background thread for emergency controls
# ---------------------------------------------------------------------------

class _KeyMonitor:
    """Watches for spacebar in a background thread.

    First space sends LAND. Second space sends EMERGENCY (motors off).
    """

    def __init__(self, client: httpx.Client, base_url: str) -> None:
        self._client = client
        self._base_url = base_url
        self._abort = False
        self._emergency = False
        self._thread: threading.Thread | None = None
        self._old_settings = None

    @property
    def should_abort(self) -> bool:
        return self._abort

    @property
    def is_emergency(self) -> bool:
        return self._emergency

    def start(self) -> None:
        if not sys.stdin.isatty():
            return
        self._old_settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._abort = True
        if self._old_settings is not None:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._old_settings)
            self._old_settings = None

    def _loop(self) -> None:
        landing_sent = False
        while True:
            try:
                ready, _, _ = select.select([sys.stdin], [], [], 0.05)
            except (ValueError, OSError):
                break
            if not ready:
                continue
            try:
                ch = sys.stdin.read(1)
            except (ValueError, OSError):
                break
            if ch != " ":
                continue

            if landing_sent:
                print("\n  ⚠ EMERGENCY STOP — MOTORS OFF")
                cmd = DroneCommand(type=CommandType.EMERGENCY, issued_by="calibration")
                _post_command(self._client, self._base_url, cmd)
                self._emergency = True
                self._abort = True
                break
            else:
                print("\n  ⚠ SPACE — EMERGENCY LANDING")
                cmd = DroneCommand(type=CommandType.LAND, issued_by="calibration")
                _post_command(self._client, self._base_url, cmd)
                landing_sent = True
                self._abort = True


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


def _health_summary(health: dict) -> str:
    telemetry = health.get("telemetry", {})
    raw = telemetry.get("raw") or {}
    adapter = health.get("adapter") or {}
    trim = adapter.get("hover_trim") or {}
    return (
        f"connected={telemetry.get('connected')} "
        f"flying={telemetry.get('flying')} "
        f"battery={telemetry.get('battery')} "
        f"h={telemetry.get('height_cm')} "
        f"tof={raw.get('tof')} "
        f"pitch={raw.get('pitch')} "
        f"roll={raw.get('roll')} "
        f"yaw={raw.get('yaw')} "
        f"trim_enabled={adapter.get('hover_trim_enabled')} "
        f"trim=({trim.get('left_right')},{trim.get('forward_back')},{trim.get('up_down')},{trim.get('yaw')})"
    )


def _abort(msg: str) -> None:
    _print_error(f"ABORT: {msg}")
    sys.exit(1)


def _assert_safe_health(health: dict, *, cfg: CalibConfig, require_flying: bool, action: str) -> None:
    telemetry = health.get("telemetry", {})
    battery = telemetry.get("battery")
    connected = telemetry.get("connected")
    flying = telemetry.get("flying")
    if connected is not True:
        _abort(f"{action}: drone is not connected: {_health_summary(health)}")
    if require_flying and flying is not True:
        _abort(f"{action}: drone is not flying: {_health_summary(health)}")
    if battery is None:
        _abort(f"{action}: battery telemetry unavailable: {_health_summary(health)}")
    if battery < cfg.min_battery:
        _abort(
            f"{action}: battery {battery}% is below calibration minimum "
            f"{cfg.min_battery}%: {_health_summary(health)}"
        )
    if not cfg.allow_hover_trim and _has_non_neutral_hover_trim(health):
        _abort(
            f"{action}: hover trim is enabled; disable trim or pass --allow-hover-trim: "
            f"{_health_summary(health)}"
        )


def _has_non_neutral_hover_trim(health: dict) -> bool:
    adapter = health.get("adapter") or {}
    if adapter.get("hover_trim_enabled") is not True:
        return False
    trim = adapter.get("hover_trim") or {}
    for key in ("left_right", "forward_back", "up_down", "yaw"):
        try:
            if int(trim.get(key) or 0) != 0:
                return True
        except (TypeError, ValueError):
            return True
    return False


# ---------------------------------------------------------------------------
# Console helpers
# ---------------------------------------------------------------------------

_SEP = "=" * 64


def _print_header(text: str) -> None:
    print(f"\n{_SEP}")
    print(f"  {text}")
    print(_SEP)


def _print_error(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)


def _confirm(cfg: CalibConfig, label: str) -> None:
    if not cfg.confirm_each:
        return
    if not sys.stdin.isatty():
        return
    input(f"\nPress Enter to run {label} (SPACE remains emergency once airborne)...")


# ---------------------------------------------------------------------------
# Maneuver runner
# ---------------------------------------------------------------------------

def _run_maneuver(
    client: httpx.Client,
    base_url: str,
    name: str,
    n_steps: int,
    build_fn,
    keys: _KeyMonitor | None = None,
) -> tuple[int, int]:
    """Send n_steps sequential commands built by build_fn(step_index).

    Returns (ok_count, fail_count).
    """
    ok_count = 0
    fail_count = 0
    width = len(str(n_steps))
    for i in range(n_steps):
        if keys and keys.should_abort:
            print(f"  — aborted at step {i}/{n_steps}")
            fail_count += n_steps - i
            break
        cmd = build_fn(i)
        ok, reason = _post_command(client, base_url, cmd)
        step_num = str(i + 1).rjust(width)
        if ok:
            print(f"  step {step_num}/{n_steps} ✓")
            ok_count += 1
        else:
            print(f"  step {step_num}/{n_steps} ✗  ({reason})")
            fail_count += 1
            fail_count += n_steps - i - 1
            break
    return ok_count, fail_count


def _climb_after_takeoff(client: httpx.Client, base_url: str, cfg: CalibConfig) -> None:
    remaining_cm = max(0, min(150, int(cfg.takeoff_climb_cm)))
    speed_cm_s = 20
    pulse_cm = 20
    index = 0
    while remaining_cm > 0:
        index += 1
        current_cm = min(pulse_cm, remaining_cm)
        duration_ms = max(300, min(1000, int(current_cm / speed_cm_s * 1000)))
        print(f"  climb pulse {index}: {current_cm}cm/{cfg.takeoff_climb_cm}cm")
        cmd = DroneCommand(
            type=CommandType.RC_CONTROL,
            issued_by="calibration",
            ttl_ms=duration_ms + 200,
            payload=RCControlPayload(duration_ms=duration_ms, up_down=speed_cm_s),
        )
        ok, reason = _post_command(client, base_url, cmd)
        if not ok:
            _abort(f"takeoff climb failed: {reason}")
        remaining_cm -= current_cm
        sleep(0.25)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _print_summary(results: list[tuple[str, int, int]]) -> None:
    _print_header("CALIBRATION SUMMARY")
    all_pass = True
    for name, ok, total in results:
        tag = "[PASS]" if ok == total else "[FAIL]"
        if ok != total:
            all_pass = False
        print(f"  {tag}  {name:<18}  {ok}/{total}")

    print()
    if all_pass:
        print("  All maneuvers completed successfully.")
    else:
        print("  Some maneuvers had failures. Review output above.")
    print()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_calibration(
    base_url: str = "http://127.0.0.1:8000",
    cfg: CalibConfig | None = None,
    log_dir: str | None = "logs",
    run_id: str | None = None,
) -> int:
    """Run the aggressive calibration sequence.  Returns 0 on full success, 1 if any maneuver failed."""
    if cfg is None:
        cfg = CalibConfig()

    client = httpx.Client()
    results: list[tuple[str, int, int]] = []

    # --- Health check ---
    _print_header("BreachEye Calibration — Aggressive Flight Test")
    print("Checking harness health...")
    health = _health_check(client, base_url)

    mode = health.get("mode", "unknown")
    telemetry = health.get("telemetry", {})
    connected = telemetry.get("connected", False)
    battery = telemetry.get("battery")

    print(f"  mode:      {mode}")
    print(f"  connected: {connected}")
    print(f"  battery:   {battery}%")
    print(f"  health:    {_health_summary(health)}")

    if mode != "tello":
        print(f"\n[WARN] harness is in '{mode}' mode, not 'tello'. Commands will run but no physical motion will occur.")
    _assert_safe_health(health, cfg=cfg, require_flying=False, action="preflight")

    # --- Takeoff ---
    _print_header("TAKEOFF")
    _confirm(cfg, "takeoff")
    takeoff_cmd = DroneCommand(type=CommandType.TAKEOFF, issued_by="calibration")
    ok, reason = _post_command(client, base_url, takeoff_cmd)
    if not ok:
        _abort(f"takeoff failed: {reason}")
    print("Takeoff executed.")

    post_takeoff = _health_check(client, base_url)
    _assert_safe_health(post_takeoff, cfg=cfg, require_flying=True, action="post-takeoff")
    _post_command(client, base_url, DroneCommand(type=CommandType.HOVER, issued_by="calibration"))
    if cfg.takeoff_climb_cm > 0:
        _climb_after_takeoff(client, base_url, cfg)

    step_ms = cfg.step_duration_ms

    # --- Start keyboard monitor ---
    keys = _KeyMonitor(client, base_url)
    keys.start()
    print("\n  Controls: SPACE = emergency land | SPACE×2 = kill motors\n")

    try:
        sequence_failed = False
        # --- Rotation left ---
        if not keys.should_abort and not sequence_failed:
            _confirm(cfg, "rotation_left")
            print("[ROTATION LEFT]  360° yaw left...")

            def _rot_left(_i):
                return DroneCommand(
                    type=CommandType.RC_CONTROL,
                    issued_by="calibration",
                    ttl_ms=step_ms + 200,
                    payload=RCControlPayload(duration_ms=step_ms, yaw=-cfg.yaw_speed),
                )

            ok_n, fail_n = _run_maneuver(client, base_url, "rotation_left", cfg.rotation_steps, _rot_left, keys)
            print(f"  Done: {ok_n}/{cfg.rotation_steps}")
            results.append(("rotation_left", ok_n, cfg.rotation_steps))
            sequence_failed = fail_n > 0

        # --- Rotation right ---
        if not keys.should_abort and not sequence_failed:
            _confirm(cfg, "rotation_right")
            print("\n[ROTATION RIGHT] 360° yaw right...")

            def _rot_right(_i):
                return DroneCommand(
                    type=CommandType.RC_CONTROL,
                    issued_by="calibration",
                    ttl_ms=step_ms + 200,
                    payload=RCControlPayload(duration_ms=step_ms, yaw=cfg.yaw_speed),
                )

            ok_n, fail_n = _run_maneuver(client, base_url, "rotation_right", cfg.rotation_steps, _rot_right, keys)
            print(f"  Done: {ok_n}/{cfg.rotation_steps}")
            results.append(("rotation_right", ok_n, cfg.rotation_steps))
            sequence_failed = fail_n > 0

        # --- Circle left ---
        if not keys.should_abort and not sequence_failed:
            _confirm(cfg, "circle_left")
            print("\n[CIRCLE LEFT]    3ft radius circle left...")

            def _circle_left(_i):
                return DroneCommand(
                    type=CommandType.RC_CONTROL,
                    issued_by="calibration",
                    ttl_ms=step_ms + 200,
                    payload=RCControlPayload(
                        duration_ms=step_ms,
                        forward_back=cfg.circle_forward,
                        yaw=-cfg.circle_yaw,
                    ),
                )

            ok_n, fail_n = _run_maneuver(client, base_url, "circle_left", cfg.circle_steps, _circle_left, keys)
            print(f"  Done: {ok_n}/{cfg.circle_steps}")
            results.append(("circle_left", ok_n, cfg.circle_steps))
            sequence_failed = fail_n > 0

        # --- Circle right ---
        if not keys.should_abort and not sequence_failed:
            _confirm(cfg, "circle_right")
            print("\n[CIRCLE RIGHT]   3ft radius circle right...")

            def _circle_right(_i):
                return DroneCommand(
                    type=CommandType.RC_CONTROL,
                    issued_by="calibration",
                    ttl_ms=step_ms + 200,
                    payload=RCControlPayload(
                        duration_ms=step_ms,
                        forward_back=cfg.circle_forward,
                        yaw=cfg.circle_yaw,
                    ),
                )

            ok_n, fail_n = _run_maneuver(client, base_url, "circle_right", cfg.circle_steps, _circle_right, keys)
            print(f"  Done: {ok_n}/{cfg.circle_steps}")
            results.append(("circle_right", ok_n, cfg.circle_steps))
            sequence_failed = fail_n > 0

        # --- Flip ---
        if not keys.should_abort and not sequence_failed and cfg.enable_flip:
            _confirm(cfg, "flip")
            print("\n[FLIP]           forward flip...")
            if battery is not None and battery < 50:
                print(f"  skipped — battery {battery}% < 50%")
                results.append(("flip", 0, 1))
            else:
                flip_cmd = DroneCommand(
                    type=CommandType.FLIP,
                    issued_by="calibration",
                    payload=FlipPayload(direction="forward"),
                )
                ok, reason = _post_command(client, base_url, flip_cmd)
                if ok:
                    print("  ✓ flip executed")
                    results.append(("flip", 1, 1))
                else:
                    print(f"  ✗ flip failed: {reason}")
                    results.append(("flip", 0, 1))

        # --- Land ---
        if not keys.is_emergency:
            _print_header("LAND")
            _confirm(cfg, "land")
            land_cmd = DroneCommand(type=CommandType.LAND, issued_by="calibration")
            ok, reason = _post_command(client, base_url, land_cmd)
            if ok:
                results.append(("land", 1, 1))
            else:
                _print_error(f"land failed: {reason}")
                results.append(("land", 0, 1))

    finally:
        keys.stop()

    # --- Summary ---
    _print_summary(results)

    failed_any = any(ok < total for _, ok, total in results)
    return 1 if failed_any else 0


def _parse_args(argv: list[str] | None = None):
    import argparse

    parser = argparse.ArgumentParser(
        prog="breacheye calibrate",
        description="Aggressive flight test: 360° rotations, 3ft circles, and a flip.",
    )
    parser.add_argument(
        "--harness-url",
        default="http://127.0.0.1:8000",
        help="Base URL of the running harness (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--yaw-speed",
        type=int,
        default=30,
        help="RC yaw value for rotations, 1-100 (default: 30)",
    )
    parser.add_argument(
        "--rotation-steps",
        type=int,
        default=12,
        help="Number of steps per full rotation (default: 12)",
    )
    parser.add_argument(
        "--circle-speed",
        type=int,
        default=30,
        help="Forward speed during circles, 1-100 (default: 30)",
    )
    parser.add_argument(
        "--circle-yaw",
        type=int,
        default=20,
        help="Yaw rate during circles — lower = wider radius (default: 20)",
    )
    parser.add_argument(
        "--circle-steps",
        type=int,
        default=18,
        help="Number of steps per full circle (default: 18)",
    )
    parser.add_argument(
        "--step-ms",
        type=int,
        default=1000,
        help="Duration of each RC sub-step in ms (default: 1000)",
    )
    parser.add_argument(
        "--no-flip",
        action="store_true",
        help="Skip flip maneuver",
    )
    parser.add_argument(
        "--takeoff-climb-cm",
        type=int,
        default=60,
        metavar="CM",
        help="Extra climb after takeoff before horizontal tests. Use 0 to disable (default: 60)",
    )
    parser.add_argument(
        "--min-battery",
        type=int,
        default=30,
        metavar="PERCENT",
        help="Minimum battery required before and during calibration (default: 30)",
    )
    parser.add_argument(
        "--allow-hover-trim",
        action="store_true",
        help="Allow non-neutral harness hover trim during calibration.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Run without pressing Enter before each action.",
    )
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--run-id")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
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
    exit_code = run_calibration(
        base_url=args.harness_url,
        cfg=cfg,
        log_dir=args.log_dir,
        run_id=args.run_id,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
