from __future__ import annotations

import asyncio
import logging
import os
from time import monotonic

from breacheye.models import CommandType, DroneCommand, RCControlPayload
from breacheye.rafa.codec import decode_navigation
from breacheye.rafa.schemas import NavigationDecision
from breacheye.runlog import RunLogger

logger = logging.getLogger("breacheye.nav_interpreter")
_GUARD_SKIP = object()


class NavInterpreter:
    def __init__(
        self,
        endpoint: str = "tcp://127.0.0.1:5558",
        command_url: str = "http://localhost:8000/commands",
        log_dir: str | None = "logs",
        run_id: str | None = None,
        bus: object | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.command_url = command_url
        self.logger = RunLogger("nav_interpreter", log_dir=log_dir, run_id=run_id)
        self._bus = bus
        self._latest_alert: dict | None = None
        self._alert_task: object | None = None
        self._depth_threshold: float = _env_float("BREACHEYE_NAV_MIN_FORWARD_CLEARANCE_M", 0.45, minimum=0.0, maximum=1.0)
        self._transit_abort_threshold: float = _env_float("BREACHEYE_DOORWAY_ABORT_DEPTH", 0.16, minimum=0.0, maximum=1.0)
        self._socket = None
        self._client = None  # httpx.AsyncClient
        self._poller = None
        self._consecutive_failures: int = 0
        self._forward_streak: int = 0
        self._hover_streak: int = 0
        self._max_forward_streak: int = _env_int("BREACHEYE_NAV_MAX_FORWARD_STREAK", 3, minimum=1, maximum=20)
        self._max_hover_streak: int = _env_int("BREACHEYE_NAV_MAX_HOVER_STREAK", 4, minimum=1, maximum=30)
        self._enable_hover_scan: bool = _env_bool("BREACHEYE_NAV_ENABLE_HOVER_SCAN", False)
        self._max_move_duration_ms: int = _env_int("BREACHEYE_NAV_MAX_MOVE_DURATION_MS", 350, minimum=50, maximum=1000)
        self._max_yaw_duration_ms: int = _env_int("BREACHEYE_NAV_MAX_YAW_DURATION_MS", 500, minimum=100, maximum=1000)
        self._airborne_settle_s: float = _env_float("BREACHEYE_NAV_AIRBORNE_SETTLE_S", 3.0, minimum=0.0, maximum=15.0)
        self._max_abs_attitude_deg: int = _env_int("BREACHEYE_NAV_MAX_ABS_ATTITUDE_DEG", 45, minimum=10, maximum=90)
        self._first_airborne_at: float | None = None
        self._battery_threshold: int = 15

    def start(self) -> None:
        import zmq
        import zmq.asyncio

        context = zmq.asyncio.Context.instance()
        self._socket = context.socket(zmq.SUB)
        self._socket.setsockopt(zmq.SUBSCRIBE, b"")
        self._socket.setsockopt(zmq.CONFLATE, 1)
        self._socket.connect(self.endpoint)

        import httpx

        self._client = httpx.AsyncClient()

        self._poller = zmq.asyncio.Poller()
        self._poller.register(self._socket, zmq.POLLIN)
        self.logger.event("nav_interpreter_start", endpoint=self.endpoint, command_url=self.command_url)

        if self._bus is not None:
            self._alert_task = asyncio.create_task(self._subscribe_alerts())

    async def _subscribe_alerts(self) -> None:
        """Subscribe to obstacle alerts on the bus. Keeps only latest (CONFLATE pattern)."""
        try:
            queue = await self._bus.subscribe("drone.obstacle_alert")
            while True:
                try:
                    self._latest_alert = await queue.get()
                except asyncio.CancelledError:
                    await self._bus.unsubscribe("drone.obstacle_alert", queue)
                    raise
        except asyncio.CancelledError:
            pass

    async def aclose(self) -> None:
        if self._alert_task is not None:
            self._alert_task.cancel()
            try:
                await self._alert_task
            except (asyncio.CancelledError, Exception):
                pass
            self._alert_task = None
        if self._socket is not None:
            self._socket.close(linger=0)
            self._socket = None
        if self._poller is not None:
            self._poller = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self.logger.event("nav_interpreter_stop")

    async def run_forever(self) -> None:
        while True:
            await self.run_once()

    async def run_once(self) -> bool:
        import zmq

        assert self._socket is not None, "call start() before run_once()"
        assert self._poller is not None, "call start() before run_once()"

        events = await self._poller.poll(timeout=500)
        if not events:
            return False

        try:
            data = await self._socket.recv(zmq.NOBLOCK)
        except zmq.Again:
            return False

        # Step 1: Decode
        try:
            nav = decode_navigation(data)
        except Exception:
            self._consecutive_failures += 1
            logger.warning(
                "malformed frame failures=%d raw=%.200s",
                self._consecutive_failures, repr(data[:200]),
            )
            self.logger.event(
                "navigation_decode_failed",
                failures=self._consecutive_failures,
                raw=repr(data[:200]),
            )
            await self._handle_failure()
            return False

        logger.info(
            "recv frame=%d action=%s confidence=%.2f",
            nav.frame_id, nav.decision.action, nav.decision.confidence,
        )
        self.logger.event(
            "navigation_received",
            frame_id=nav.frame_id,
            action=nav.decision.action,
            confidence=nav.decision.confidence,
            reasoning=nav.decision.reasoning,
            params=nav.decision.params,
            exploration_state=nav.decision.exploration_state,
        )
        await self._post_navigation_event(nav.model_dump(mode="json"))

        # Step 2: Confidence check
        if nav.decision.confidence < 0.5:
            self._consecutive_failures += 1
            logger.warning(
                "low_confidence frame=%d confidence=%.2f reasoning=%s failures=%d",
                nav.frame_id, nav.decision.confidence,
                nav.decision.reasoning, self._consecutive_failures,
            )
            self.logger.event(
                "navigation_low_confidence",
                frame_id=nav.frame_id,
                confidence=nav.decision.confidence,
                failures=self._consecutive_failures,
                reasoning=nav.decision.reasoning,
            )
            await self._handle_failure()
            return False

        # Step 3: Map and execute
        try:
            guarded_cmd = await self._guard_command_for_health(nav.frame_id, nav.decision)
            if guarded_cmd is _GUARD_SKIP:
                return False
            cmd = guarded_cmd if isinstance(guarded_cmd, DroneCommand) else self._map_action(nav.decision)
            await self._post_command(cmd)
            self._consecutive_failures = 0  # Reset on success
            self.logger.event(
                "navigation_executed",
                frame_id=nav.frame_id,
                command_id=cmd.command_id,
                command_type=cmd.type.value,
            )
            return True
        except Exception:
            self._consecutive_failures += 1
            logger.exception("map_error failures=%d", self._consecutive_failures)
            self.logger.event("navigation_map_failed", failures=self._consecutive_failures)
            await self._handle_failure()
            return False

    def _map_action(self, decision: NavigationDecision) -> DroneCommand:
        action = self._guard_action(decision)

        if action == "hover":
            cmd = DroneCommand(type=CommandType.HOVER, issued_by="nav_interpreter")
            logger.info("send type=%s cmd_id=%s", cmd.type, cmd.command_id)
            return cmd

        if action == "land":
            cmd = DroneCommand(type=CommandType.LAND, issued_by="nav_interpreter")
            logger.info("send type=%s cmd_id=%s", cmd.type, cmd.command_id)
            return cmd

        # RC_CONTROL actions
        speed = max(1, min(100, int(decision.params.get("speed_cm_s", 30))))

        if action in ("move_up", "move_down"):
            distance = int(decision.params.get("distance_cm", 25))
        else:
            distance = int(decision.params.get("distance_cm", 40))

        if action in ("rotate_left", "rotate_right"):
            degrees = decision.params.get("degrees", 30)
            duration_ms = max(100, min(self._max_yaw_duration_ms, int(float(degrees) / 90 * 1000)))
        else:
            duration_ms = max(100, min(self._max_move_duration_ms, int(distance / max(speed, 1) * 1000)))

        ttl_ms = min(1200, duration_ms + 200)

        vel_map = {
            "move_forward": {"forward_back": speed},
            "move_back": {"forward_back": -speed},
            "move_left": {"left_right": -speed},
            "move_right": {"left_right": speed},
            "move_up": {"up_down": speed},
            "move_down": {"up_down": -speed},
            "rotate_left": {"yaw": -25},
            "rotate_right": {"yaw": 25},
        }

        axes = vel_map[action]
        payload = RCControlPayload(duration_ms=duration_ms, **axes)

        cmd = DroneCommand(
            type=CommandType.RC_CONTROL,
            issued_by="nav_interpreter",
            ttl_ms=ttl_ms,
            payload=payload,
        )
        logger.info("send type=%s cmd_id=%s", cmd.type, cmd.command_id)
        return cmd

    def _guard_action(self, decision: NavigationDecision) -> str:
        transit = _is_transit_decision(decision)
        relax_depth_guard = transit and _truthy(decision.params.get("relax_depth_guard"))

        # Depth guard — blocks forward movement when obstacle detected
        if decision.action == "move_forward" and self._latest_alert is not None:
            alert = self._latest_alert
            zones = alert.get("zones") or {}
            nearest = alert.get("nearest_obstacle_m")
            if nearest is None:
                nearest = alert.get("min_depth", 1.0)
            center_depth = zones.get("center", alert.get("mean_center_depth", nearest))
            if center_depth is None:
                center_depth = nearest
            guard_depth = center_depth if relax_depth_guard else nearest
            blocked = bool(alert.get("blocked", alert.get("obstacle_detected", False)))
            threshold = self._transit_abort_threshold if relax_depth_guard else self._depth_threshold
            hard_blocked = guard_depth < threshold or (blocked and not relax_depth_guard)
            if hard_blocked:
                self.logger.event(
                    "navigation_transit_depth_guard" if relax_depth_guard else "navigation_depth_guard",
                    frame_id=alert.get("frame_id"),
                    requested_action="move_forward",
                    substituted_action="rotate_right",
                    nearest=nearest,
                    guard_depth=guard_depth,
                    zones=alert.get("zones"),
                    threshold=threshold,
                    transit=transit,
                )
                self._forward_streak = 0
                return "rotate_right"

        if transit:
            self._forward_streak = 0
            self._hover_streak = 0
            return decision.action

        if decision.action == "move_forward":
            self._forward_streak += 1
            self._hover_streak = 0
            if self._forward_streak > self._max_forward_streak:
                self.logger.event(
                    "navigation_forward_streak_guard",
                    requested_action=decision.action,
                    substituted_action="rotate_right",
                    forward_streak=self._forward_streak,
                    max_forward_streak=self._max_forward_streak,
                )
                self._forward_streak = 0
                return "rotate_right"
            return "move_forward"
        if decision.action == "hover":
            self._forward_streak = 0
            self._hover_streak += 1
            if self._enable_hover_scan and self._hover_streak > self._max_hover_streak:
                self.logger.event(
                    "navigation_hover_scan_guard",
                    requested_action=decision.action,
                    substituted_action="rotate_right",
                    hover_streak=self._hover_streak,
                    max_hover_streak=self._max_hover_streak,
                )
                self._hover_streak = 0
                return "rotate_right"
            return "hover"
        self._forward_streak = 0
        self._hover_streak = 0
        return decision.action

    async def _guard_command_for_health(self, frame_id: int, decision: NavigationDecision):
        health = await self._get_health_payload()
        telemetry = health.get("telemetry", {}) if health else {}
        if telemetry.get("flying") is not True:
            return _GUARD_SKIP

        if health.get("accepts_nav") is False:
            self.logger.event(
                "navigation_paused_guard",
                frame_id=frame_id,
                requested_action=decision.action,
            )
            logger.info("paused — skipping nav frame=%d action=%s", frame_id, decision.action)
            return _GUARD_SKIP

        now = monotonic()
        if self._first_airborne_at is None:
            self._first_airborne_at = now

        attitude_reasons = self._unsafe_attitude_reasons(telemetry)
        if attitude_reasons:
            self._forward_streak = 0
            self._hover_streak = 0
            cmd = DroneCommand(type=CommandType.EMERGENCY, issued_by="nav_interpreter_attitude_guard")
            self.logger.event(
                "navigation_flight_state_guard",
                frame_id=frame_id,
                requested_action=decision.action,
                substituted_command=cmd.type.value,
                reason="; ".join(attitude_reasons),
                telemetry=telemetry,
            )
            return cmd

        if _is_movement_action(decision.action) and now - self._first_airborne_at < self._airborne_settle_s:
            self._forward_streak = 0
            self._hover_streak = 0
            cmd = DroneCommand(type=CommandType.HOVER, issued_by="nav_interpreter_settle_guard")
            self.logger.event(
                "navigation_flight_state_guard",
                frame_id=frame_id,
                requested_action=decision.action,
                substituted_command=cmd.type.value,
                reason=f"airborne settle window {now - self._first_airborne_at:.1f}s < {self._airborne_settle_s:.1f}s",
                telemetry=telemetry,
            )
            return cmd

        return None

    def _unsafe_attitude_reasons(self, telemetry: dict) -> list[str]:
        raw = telemetry.get("raw") or {}
        reasons: list[str] = []
        pitch = _float_or_none(raw.get("pitch"))
        roll = _float_or_none(raw.get("roll"))
        if pitch is not None and abs(pitch) >= self._max_abs_attitude_deg:
            reasons.append(f"pitch={pitch:g}")
        if roll is not None and abs(roll) >= self._max_abs_attitude_deg:
            reasons.append(f"roll={roll:g}")
        height_cm = _float_or_none(telemetry.get("height_cm"))
        tof = _float_or_none(raw.get("tof"))
        if height_cm is not None and height_cm <= 0 and tof is not None and tof <= 40:
            reasons.append(f"height_cm={height_cm:g} tof={tof:g}")
        return reasons

    async def _handle_failure(self) -> None:
        try:
            if self._consecutive_failures >= 3:
                battery = await self._get_battery()
                if battery is not None and battery <= self._battery_threshold:
                    logger.warning(
                        "escalation: %d consecutive failures, battery=%d%%, landing",
                        self._consecutive_failures, battery,
                    )
                    cmd = DroneCommand(type=CommandType.LAND, issued_by="nav_interpreter")
                else:
                    logger.warning(
                        "escalation: %d consecutive failures, holding hover (battery=%s%%)",
                        self._consecutive_failures, battery,
                    )
                    cmd = DroneCommand(type=CommandType.HOVER, issued_by="nav_interpreter")
            else:
                cmd = DroneCommand(type=CommandType.HOVER, issued_by="nav_interpreter")
            self.logger.event(
                "navigation_failure_action",
                failures=self._consecutive_failures,
                command_id=cmd.command_id,
                command_type=cmd.type.value,
            )
            await self._post_command(cmd)
        except Exception:
            logger.exception("handle_failure itself failed, failures=%d", self._consecutive_failures)
            self.logger.event("navigation_failure_handler_failed", failures=self._consecutive_failures)

    async def _get_battery(self) -> int | None:
        payload = await self._get_health_payload()
        if payload:
            return payload.get("telemetry", {}).get("battery")
        return None

    async def _get_health_payload(self) -> dict | None:
        assert self._client is not None, "call start() before _get_health_payload()"
        try:
            health_url = self.command_url.rsplit("/", 1)[0] + "/health"
            resp = await self._client.get(health_url)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            logger.warning("failed to fetch flight state")
        return None

    async def _post_command(self, cmd: DroneCommand) -> None:
        assert self._client is not None, "call start() before _post_command()"
        resp = await self._client.post(self.command_url, json=cmd.model_dump(mode="json"))
        response_status = None
        response_reason = None
        try:
            response_payload = resp.json()
            response_status = response_payload.get("status")
            response_reason = response_payload.get("reason")
        except Exception:
            pass
        self.logger.event(
            "command_posted",
            command_id=cmd.command_id,
            command_type=cmd.type.value,
            command_payload=cmd.payload.model_dump(mode="json") if cmd.payload else None,
            command_ttl_ms=cmd.ttl_ms,
            status_code=resp.status_code,
            response_status=response_status,
            response_reason=response_reason,
        )
        if resp.status_code != 200:
            logger.warning("post failed status=%d", resp.status_code)
            raise RuntimeError(f"command post failed status={resp.status_code}")
        if response_status != "executed":
            reason = response_reason or response_status or "missing command response body"
            logger.warning("command failed cmd_id=%s status=%s reason=%s", cmd.command_id, response_status, reason)
            raise RuntimeError(f"command {cmd.command_id} failed: {reason}")

    async def _post_navigation_event(self, payload: dict) -> None:
        if self._client is None:
            return
        event_url = self.command_url.rsplit("/", 1)[0] + "/events/navigation"
        try:
            response = await self._client.post(event_url, json=payload)
            self.logger.event(
                "navigation_event_posted",
                frame_id=payload.get("frame_id"),
                status_code=response.status_code,
            )
        except Exception as exc:
            self.logger.event(
                "navigation_event_post_failed",
                frame_id=payload.get("frame_id"),
                error=str(exc),
            )


def _is_movement_action(action: str) -> bool:
    return action in {
        "move_forward",
        "move_back",
        "move_left",
        "move_right",
        "move_up",
        "move_down",
        "rotate_left",
        "rotate_right",
    }


def _is_transit_decision(decision: NavigationDecision) -> bool:
    state = str(decision.exploration_state)
    return state.startswith("doorway_") or "transit_phase" in decision.params


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _float_or_none(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
