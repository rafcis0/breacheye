import asyncio
from time import monotonic

import pytest

from breacheye.adapters.base import DroneState
from breacheye.adapters.sim import SimAdapter
from breacheye.bus import AsyncEventBus
from breacheye.models import CommandStatus, CommandType, DroneCommand, RCControlPayload
from breacheye.safety import SafetyConfig, SafetyController


@pytest.mark.asyncio
async def test_rc_control_is_clamped_and_returns_to_hover() -> None:
    adapter = SimAdapter()
    await adapter.connect()
    await adapter.takeoff()
    controller = SafetyController(
        adapter,
        AsyncEventBus(),
        SafetyConfig(max_abs_velocity=20, default_ttl_ms=250, max_rc_duration_ms=250),
    )

    result = await controller.execute(
        DroneCommand(
            type=CommandType.RC_CONTROL,
            issued_by="test",
            ttl_ms=250,
            payload=RCControlPayload(
                left_right=100,
                forward_back=-100,
                up_down=15,
                yaw=30,
                duration_ms=50,
            ),
        )
    )

    assert result.status == CommandStatus.EXECUTED
    assert ("rc_control", (20, -20, 15, 20)) in adapter.commands
    assert adapter.commands[-1] == ("hover", (0, 0, 0, 0))


@pytest.mark.asyncio
async def test_rc_control_rejects_duration_longer_than_ttl() -> None:
    adapter = SimAdapter()
    await adapter.connect()
    await adapter.takeoff()
    controller = SafetyController(adapter, AsyncEventBus())

    result = await controller.execute(
        DroneCommand(
            type=CommandType.RC_CONTROL,
            issued_by="test",
            ttl_ms=50,
            payload=RCControlPayload(duration_ms=100),
        )
    )

    assert result.status == CommandStatus.FAILED
    assert "duration_ms" in (result.reason or "")


@pytest.mark.asyncio
async def test_hover_noops_when_grounded() -> None:
    adapter = SimAdapter()
    await adapter.connect()
    controller = SafetyController(adapter, AsyncEventBus())

    result = await controller.execute(DroneCommand(type=CommandType.HOVER, issued_by="test"))

    assert result.status == CommandStatus.EXECUTED
    assert ("hover", (0, 0, 0, 0)) not in adapter.commands


@pytest.mark.asyncio
async def test_rc_control_rejects_when_grounded() -> None:
    adapter = SimAdapter()
    await adapter.connect()
    controller = SafetyController(adapter, AsyncEventBus())

    result = await controller.execute(
        DroneCommand(
            type=CommandType.RC_CONTROL,
            issued_by="test",
            payload=RCControlPayload(duration_ms=100),
        )
    )

    assert result.status == CommandStatus.FAILED
    assert "not flying" in (result.reason or "")


@pytest.mark.asyncio
async def test_watchdog_hovers_after_stale_command() -> None:
    adapter = SimAdapter()
    await adapter.connect()
    await adapter.takeoff()
    controller = SafetyController(
        adapter,
        AsyncEventBus(),
        SafetyConfig(watchdog_interval_s=0.01, stale_command_s=0.01, keepalive_interval_s=60),
    )
    await controller.start()
    try:
        await asyncio.sleep(0.05)
    finally:
        await controller.stop()

    assert ("hover", (0, 0, 0, 0)) in adapter.commands


@pytest.mark.asyncio
async def test_watchdog_does_not_keepalive_when_grounded() -> None:
    adapter = SimAdapter()
    await adapter.connect()
    controller = SafetyController(
        adapter,
        AsyncEventBus(),
        SafetyConfig(watchdog_interval_s=0.01, stale_command_s=0.01, keepalive_interval_s=0.01),
    )
    await controller.start()
    try:
        await asyncio.sleep(0.05)
    finally:
        await controller.stop()

    assert ("keepalive", ()) not in adapter.commands


@pytest.mark.asyncio
async def test_watchdog_does_not_interleave_with_active_command() -> None:
    class SlowLandAdapter(SimAdapter):
        async def land(self) -> None:
            self.commands.append(("land_start", ()))
            await asyncio.sleep(0.05)
            await super().land()

        async def get_state(self) -> DroneState:
            state = await super().get_state()
            return DroneState(
                connected=state.connected,
                flying=True,
                battery=state.battery,
                height_cm=state.height_cm,
                flight_time_s=state.flight_time_s,
                raw=state.raw,
            )

    adapter = SlowLandAdapter()
    await adapter.connect()
    await adapter.takeoff()
    controller = SafetyController(
        adapter,
        AsyncEventBus(),
        SafetyConfig(watchdog_interval_s=0.005, stale_command_s=0.0, keepalive_interval_s=0.0),
    )
    await controller.start()
    try:
        controller._last_command_at = monotonic() - 10
        controller._last_keepalive_at = monotonic() - 10
        result = await controller.execute(DroneCommand(type=CommandType.LAND, issued_by="test"))
    finally:
        await controller.stop()

    assert result.status == CommandStatus.EXECUTED
    land_start = [index for index, command in enumerate(adapter.commands) if command[0] == "land_start"][0]
    land_done = [index for index, command in enumerate(adapter.commands) if command[0] == "land"][0]
    between = adapter.commands[land_start + 1 : land_done]
    assert all(command[0] not in {"hover", "keepalive"} for command in between)
