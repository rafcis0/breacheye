from __future__ import annotations

import pytest

from breacheye import calibration
from breacheye.calibration import CalibConfig, run_calibration
from breacheye.models import DroneCommand


def _health(*, flying: bool, battery: int = 80, trim_enabled: bool = False) -> dict:
    return {
        "mode": "tello",
        "telemetry": {
            "connected": True,
            "flying": flying,
            "battery": battery,
            "height_cm": 100 if flying else 0,
            "raw": {"tof": 120 if flying else 10, "pitch": 0, "roll": 0, "yaw": 0},
        },
        "adapter": {
            "hover_trim_enabled": trim_enabled,
            "hover_trim": {
                "left_right": -4 if trim_enabled else 0,
                "forward_back": 6 if trim_enabled else 0,
                "up_down": 0,
                "yaw": 0,
            },
        },
    }


def test_calibration_refuses_non_neutral_hover_trim(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(calibration, "_health_check", lambda _client, _base_url: _health(flying=False, trim_enabled=True))

    with pytest.raises(SystemExit) as exc:
        run_calibration(
            cfg=CalibConfig(confirm_each=False, min_battery=1),
            log_dir=tmp_path,
            run_id="trim-refused",
        )

    assert exc.value.code == 1


def test_calibration_stops_and_lands_on_first_command_failure(monkeypatch, tmp_path) -> None:
    healths = iter(
        [
            _health(flying=False),  # initial
            _health(flying=True),  # post-takeoff
            _health(flying=True),  # before hover
            _health(flying=True),  # after hover
            _health(flying=True),  # before move_forward
            _health(flying=True),  # after failed move_forward
            _health(flying=True),  # safe land check
        ]
    )
    commands: list[str] = []

    def fake_health(_client, _base_url):
        return next(healths)

    def fake_post(_client, _base_url, command: DroneCommand):
        commands.append(command.type.value)
        if command.type.value == "rc_control" and len(commands) == 3:
            return False, "cannot rc_control while not flying"
        return True, ""

    monkeypatch.setattr(calibration, "_health_check", fake_health)
    monkeypatch.setattr(calibration, "_post_command", fake_post)
    monkeypatch.setattr(calibration.time, "sleep", lambda _seconds: None)

    code = run_calibration(
        cfg=CalibConfig(confirm_each=False, min_battery=1, takeoff_climb_cm=0),
        log_dir=tmp_path,
        run_id="stop-on-failure",
    )

    assert code == 1
    assert commands == ["takeoff", "hover", "rc_control", "land"]
