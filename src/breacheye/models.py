from __future__ import annotations

from enum import StrEnum
from time import time
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CommandType(StrEnum):
    TAKEOFF = "takeoff"
    LAND = "land"
    EMERGENCY = "emergency"
    HOVER = "hover"
    RC_CONTROL = "rc_control"


class CommandStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"


class RCControlPayload(BaseModel):
    left_right: int = Field(default=0, ge=-100, le=100)
    forward_back: int = Field(default=0, ge=-100, le=100)
    up_down: int = Field(default=0, ge=-100, le=100)
    yaw: int = Field(default=0, ge=-100, le=100)
    duration_ms: int = Field(default=250, ge=50, le=2000)


class DroneCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(default_factory=lambda: str(uuid4()))
    type: CommandType
    issued_by: str = "unknown"
    ttl_ms: int | None = Field(default=None, ge=50, le=5000)
    payload: RCControlPayload | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> "DroneCommand":
        if self.type == CommandType.RC_CONTROL and self.payload is None:
            raise ValueError("rc_control commands require payload")
        if self.type != CommandType.RC_CONTROL and self.payload is not None:
            raise ValueError(f"{self.type} commands must not include payload")
        return self


class DroneTelemetry(BaseModel):
    timestamp: float = Field(default_factory=time)
    connected: bool = False
    flying: bool = False
    battery: int | None = None
    height_cm: int | None = None
    flight_time_s: int | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class CommandResult(BaseModel):
    command_id: str
    status: CommandStatus
    reason: str | None = None
    timestamp: float = Field(default_factory=time)


class FrameMetadata(BaseModel):
    timestamp: float = Field(default_factory=time)
    sequence: int
    width: int | None = None
    height: int | None = None
    source: Literal["sampled", "full"] = "sampled"
