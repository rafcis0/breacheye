from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DroneState:
    connected: bool = False
    flying: bool = False
    battery: int | None = None
    height_cm: int | None = None
    flight_time_s: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class DroneAdapter(ABC):
    @abstractmethod
    async def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def takeoff(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def land(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def emergency(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def hover(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def rc_control(
        self,
        left_right: int,
        forward_back: int,
        up_down: int,
        yaw: int,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def keepalive(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_state(self) -> DroneState:
        raise NotImplementedError

    async def start_video(self) -> None:
        return None

    async def stop_video(self) -> None:
        return None
