from __future__ import annotations

import asyncio
import os

from breacheye.adapters.base import DroneAdapter, DroneState


class TelloAdapter(DroneAdapter):
    """DJITelloPy-backed adapter for a physical Tello.

    Imports are intentionally lazy so simulator tests and API development do not
    require hardware dependencies. The adapter owns SDK calls only; safety policy
    stays in `SafetyController`.
    """

    def __init__(self) -> None:
        self._tello = None
        self._connected = False
        self._hover_trim_enabled = _env_bool("BREACHEYE_TELLO_ENABLE_HOVER_TRIM", False)
        self._hover_left_right = _env_int("BREACHEYE_TELLO_HOVER_LEFT_RIGHT", 0) if self._hover_trim_enabled else 0
        self._hover_forward_back = _env_int("BREACHEYE_TELLO_HOVER_FORWARD_BACK", 0) if self._hover_trim_enabled else 0
        self._hover_up_down = _env_int("BREACHEYE_TELLO_HOVER_UP_DOWN", 0) if self._hover_trim_enabled else 0
        self._hover_yaw = _env_int("BREACHEYE_TELLO_HOVER_YAW", 0) if self._hover_trim_enabled else 0

    async def connect(self) -> None:
        def _connect() -> None:
            from djitellopy import Tello

            self._tello = Tello()
            self._tello.connect()
            self._connected = True

        await asyncio.to_thread(_connect)

    async def close(self) -> None:
        if self._tello is None:
            return

        def _close() -> None:
            try:
                self._tello.end()
            finally:
                self._connected = False

        await asyncio.to_thread(_close)

    async def takeoff(self) -> None:
        await self._call("takeoff")

    async def land(self) -> None:
        await self._call("land")

    async def emergency(self) -> None:
        await self._call("emergency")

    async def hover(self) -> None:
        await self.rc_control(
            self._hover_left_right,
            self._hover_forward_back,
            self._hover_up_down,
            self._hover_yaw,
        )

    def diagnostics(self) -> dict:
        return {
            "hover_trim_enabled": self._hover_trim_enabled,
            "hover_trim": {
                "left_right": self._hover_left_right,
                "forward_back": self._hover_forward_back,
                "up_down": self._hover_up_down,
                "yaw": self._hover_yaw,
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
        await self._call(
            "send_rc_control",
            left_right,
            forward_back,
            up_down,
            yaw,
        )

    async def keepalive(self) -> None:
        # Some Tello firmware responds `unknown command: keepalive`; neutral RC
        # is accepted by SDK mode and also holds position while flying.
        await self.hover()

    async def get_state(self) -> DroneState:
        if self._tello is None:
            return DroneState(connected=False)

        def _state() -> DroneState:
            raw = dict(self._tello.get_current_state() or {})
            return DroneState(
                connected=self._connected,
                flying=bool(getattr(self._tello, "is_flying", False)),
                battery=_int_or_none(raw.get("bat")),
                height_cm=_int_or_none(raw.get("h")),
                flight_time_s=_int_or_none(raw.get("time")),
                raw=raw,
            )

        return await asyncio.to_thread(_state)

    async def flip(self, direction: str) -> None:
        await self._call(f"flip_{direction}")

    async def start_video(self) -> None:
        await self._call("streamon")

    async def stop_video(self) -> None:
        await self._call("streamoff")

    def frame_reader(self):
        if self._tello is None:
            raise RuntimeError("drone is not connected")
        return self._tello.get_frame_read()

    async def _call(self, name: str, *args) -> None:
        if self._tello is None:
            raise RuntimeError("drone is not connected")
        await asyncio.to_thread(getattr(self._tello, name), *args)


def _int_or_none(value) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _env_int(name: str, default: int) -> int:
    try:
        return max(-20, min(20, int(os.environ.get(name, default))))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
