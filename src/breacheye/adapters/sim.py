from __future__ import annotations

from time import monotonic

from breacheye.adapters.base import DroneAdapter, DroneState


class SimAdapter(DroneAdapter):
    def __init__(self) -> None:
        self.state = DroneState(connected=False, flying=False, battery=100, height_cm=0)
        self.commands: list[tuple[str, tuple[int, ...]]] = []
        self._flight_started_at: float | None = None

    async def connect(self) -> None:
        self.state.connected = True
        self.commands.append(("connect", ()))

    async def close(self) -> None:
        self.commands.append(("close", ()))
        self.state.connected = False

    async def takeoff(self) -> None:
        self._require_connected()
        self.state.flying = True
        self.state.height_cm = max(self.state.height_cm or 0, 80)
        self._flight_started_at = monotonic()
        self.commands.append(("takeoff", ()))

    async def land(self) -> None:
        self._require_connected()
        self.state.flying = False
        self.state.height_cm = 0
        self.commands.append(("land", ()))

    async def emergency(self) -> None:
        self.state.flying = False
        self.state.height_cm = 0
        self.commands.append(("emergency", ()))

    async def hover(self) -> None:
        self._require_connected()
        self.commands.append(("hover", (0, 0, 0, 0)))

    def diagnostics(self) -> dict:
        return {
            "hover_trim_enabled": False,
            "hover_trim": {
                "left_right": 0,
                "forward_back": 0,
                "up_down": 0,
                "yaw": 0,
            },
            "rc_axis_order": "left_right, forward_back, up_down, yaw",
        }

    async def rc_control(
        self,
        left_right: int,
        forward_back: int,
        up_down: int,
        yaw: int,
    ) -> None:
        self._require_connected()
        if not self.state.flying:
            raise RuntimeError("cannot rc_control while not flying")
        self.commands.append(("rc_control", (left_right, forward_back, up_down, yaw)))

    async def keepalive(self) -> None:
        self._require_connected()
        self.commands.append(("keepalive", ()))

    async def flip(self, direction: str) -> None:
        self._require_connected()
        if not self.state.flying:
            raise RuntimeError("cannot flip while not flying")
        self.commands.append(("flip", (direction,)))

    async def get_state(self) -> DroneState:
        if self._flight_started_at is not None and self.state.flying:
            self.state.flight_time_s = int(monotonic() - self._flight_started_at)
        return self.state

    def _require_connected(self) -> None:
        if not self.state.connected:
            raise RuntimeError("drone is not connected")
