from __future__ import annotations

import logging
import os

from breacheye.models import CommandType, DroneCommand, RCControlPayload
from breacheye.rafa.codec import decode_navigation
from breacheye.rafa.schemas import NavigationDecision
from breacheye.runlog import RunLogger

logger = logging.getLogger("breacheye.nav_interpreter")


class NavInterpreter:
    def __init__(
        self,
        endpoint: str = "tcp://127.0.0.1:5558",
        command_url: str = "http://localhost:8000/commands",
        log_dir: str | None = "logs",
        run_id: str | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.command_url = command_url
        self.logger = RunLogger("nav_interpreter", log_dir=log_dir, run_id=run_id)
        self._socket = None
        self._client = None  # httpx.AsyncClient
        self._poller = None
        self._consecutive_failures: int = 0
        self._forward_streak: int = 0
        self._max_forward_streak: int = int(os.environ.get("BREACHEYE_NAV_MAX_FORWARD_STREAK", "3"))
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

    async def aclose(self) -> None:
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
            cmd = self._map_action(nav.decision)
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
            duration_ms = max(100, min(800, int(float(degrees) / 90 * 1000)))
        else:
            duration_ms = max(100, min(800, int(distance / max(speed, 1) * 1000)))

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
        if decision.action == "move_forward":
            self._forward_streak += 1
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
        self._forward_streak = 0
        return decision.action

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
        try:
            health_url = self.command_url.rsplit("/", 1)[0] + "/health"
            resp = await self._client.get(health_url)
            if resp.status_code == 200:
                return resp.json().get("telemetry", {}).get("battery")
        except Exception:
            logger.warning("failed to fetch battery level")
        return None

    async def _post_command(self, cmd: DroneCommand) -> None:
        assert self._client is not None, "call start() before _post_command()"
        resp = await self._client.post(self.command_url, json=cmd.model_dump(mode="json"))
        self.logger.event(
            "command_posted",
            command_id=cmd.command_id,
            command_type=cmd.type.value,
            status_code=resp.status_code,
        )
        if resp.status_code != 200:
            logger.warning("post failed status=%d", resp.status_code)
