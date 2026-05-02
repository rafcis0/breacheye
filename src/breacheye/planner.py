from __future__ import annotations

from breacheye.models import CommandType, DroneCommand, RCControlPayload


def scripted_room_scan(issued_by: str = "mock_planner") -> list[DroneCommand]:
    """A deterministic placeholder for the future LLM planner.

    The real planner should consume `drone.telemetry` and sampled frames, then
    emit the same structured `DroneCommand` objects. This function exists so the
    harness can be exercised before model prompts and room-navigation policy are
    settled.
    """

    return [
        DroneCommand(
            type=CommandType.RC_CONTROL,
            issued_by=issued_by,
            ttl_ms=650,
            payload=RCControlPayload(yaw=25, duration_ms=400),
        ),
        DroneCommand(type=CommandType.HOVER, issued_by=issued_by),
        DroneCommand(
            type=CommandType.RC_CONTROL,
            issued_by=issued_by,
            ttl_ms=650,
            payload=RCControlPayload(yaw=-25, duration_ms=400),
        ),
        DroneCommand(type=CommandType.HOVER, issued_by=issued_by),
    ]
