from __future__ import annotations

import logging

from breacheye.models import CommandType, DroneCommand, RCControlPayload
from breacheye.rafa.codec import decode_navigation
from breacheye.rafa.schemas import NavigationDecision

logger = logging.getLogger("breacheye.nav_interpreter")


class NavInterpreter:
    def __init__(
        self,
        endpoint: str = "tcp://127.0.0.1:5558",
        command_url: str = "http://localhost:8000/commands",
    ) -> None:
        self.endpoint = endpoint
        self.command_url = command_url
        self._socket = None
        self._client = None  # httpx.AsyncClient

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

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close(linger=0)
            self._socket = None
        if self._client is not None:
            import asyncio

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self._client.aclose())
                else:
                    loop.run_until_complete(self._client.aclose())
            except Exception:
                pass
            self._client = None

    async def run_forever(self) -> None:
        while True:
            await self.run_once()

    async def run_once(self) -> bool:
        import zmq

        assert self._socket is not None, "call start() before run_once()"

        poller = zmq.asyncio.Poller()
        poller.register(self._socket, zmq.POLLIN)
        events = await poller.poll(timeout=500)
        if not events:
            return False

        try:
            data = self._socket.recv(zmq.NOBLOCK)
        except zmq.Again:
            return False

        nav = decode_navigation(data)
        logger.info(
            "recv frame=%d action=%s confidence=%.2f",
            nav.frame_id,
            nav.decision.action,
            nav.decision.confidence,
        )

        cmd = self._map_action(nav.decision)
        await self._post_command(cmd)
        return True

    def _map_action(self, decision: NavigationDecision) -> DroneCommand:
        if decision.confidence < 0.5:
            logger.info("low confidence=%.2f, overriding to hover", decision.confidence)
            return DroneCommand(type=CommandType.HOVER, issued_by="nav_interpreter")

        action = decision.action

        if action == "hover":
            cmd = DroneCommand(type=CommandType.HOVER, issued_by="nav_interpreter")
            logger.info("send type=%s cmd_id=%s", cmd.type, cmd.command_id)
            return cmd

        if action == "land":
            cmd = DroneCommand(type=CommandType.LAND, issued_by="nav_interpreter")
            logger.info("send type=%s cmd_id=%s", cmd.type, cmd.command_id)
            return cmd

        # RC_CONTROL actions
        speed = int(decision.params.get("speed_cm_s", 30))

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

    async def _post_command(self, cmd: DroneCommand) -> None:
        assert self._client is not None, "call start() before _post_command()"
        resp = await self._client.post(self.command_url, json=cmd.model_dump(mode="json"))
        if resp.status_code != 200:
            logger.warning("post failed status=%d", resp.status_code)
