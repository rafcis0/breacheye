from pydantic import ValidationError
import pytest

from breacheye.models import CommandType, DroneCommand, RCControlPayload


def test_rc_control_requires_payload() -> None:
    with pytest.raises(ValidationError):
        DroneCommand(type=CommandType.RC_CONTROL, issued_by="test")


def test_non_rc_control_rejects_payload() -> None:
    with pytest.raises(ValidationError):
        DroneCommand(
            type=CommandType.TAKEOFF,
            issued_by="test",
            payload=RCControlPayload(duration_ms=50),
        )


def test_raw_sdk_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        DroneCommand(type=CommandType.HOVER, issued_by="test", raw="flip f")
