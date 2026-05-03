from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from time import monotonic

from breacheye.adapters.base import DroneAdapter
from breacheye.bus import AsyncEventBus
from breacheye.models import (
    CommandResult,
    CommandStatus,
    CommandType,
    DroneCommand,
    DroneTelemetry,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SafetyConfig:
    max_abs_velocity: int = 35
    default_ttl_ms: int = 750
    max_rc_duration_ms: int = 1000
    min_takeoff_battery: int = 25
    watchdog_interval_s: float = 0.5
    stale_command_s: float = 2.0
    keepalive_interval_s: float = 5.0
    critical_attitude_deg: int = 60
    land_on_adapter_error: bool = False


class SafetyController:
    """Executes only short-lived structured actions against a drone adapter.

    The SDK exposes many raw commands, but this controller is the boundary an
    LLM or teammate process should target. It constrains velocity, duration,
    and stale-command behavior before anything reaches the hardware adapter.
    """

    def __init__(
        self,
        adapter: DroneAdapter,
        bus: AsyncEventBus,
        config: SafetyConfig | None = None,
    ) -> None:
        self.adapter = adapter
        self.bus = bus
        self.config = config or SafetyConfig()
        self._last_command_at = monotonic()
        self._last_keepalive_at = monotonic()
        self._watchdog_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._closed = False
        self._watchdog_emergency_sent = False

    async def start(self) -> None:
        if self._watchdog_task is None:
            self._watchdog_task = asyncio.create_task(self._watchdog_loop())

    async def stop(self) -> None:
        self._closed = True
        if self._watchdog_task is not None:
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass

    async def execute(self, command: DroneCommand) -> CommandResult:
        accepted = CommandResult(command_id=command.command_id, status=CommandStatus.ACCEPTED)
        await self.bus.publish("drone.command_results", accepted)

        async with self._lock:
            try:
                await self._execute_locked(command)
                self._last_command_at = monotonic()
            except Exception as exc:
                result = CommandResult(
                    command_id=command.command_id,
                    status=CommandStatus.FAILED,
                    reason=str(exc),
                )
                await self.bus.publish("drone.command_results", result)
                return result

        result = CommandResult(command_id=command.command_id, status=CommandStatus.EXECUTED)
        await self.bus.publish("drone.command_results", result)
        return result

    def last_command_age_s(self) -> float:
        return max(0.0, monotonic() - self._last_command_at)

    async def telemetry(self) -> DroneTelemetry:
        state = await self.adapter.get_state()
        return DroneTelemetry(
            connected=state.connected,
            flying=state.flying,
            battery=state.battery,
            height_cm=state.height_cm,
            flight_time_s=state.flight_time_s,
            raw=state.raw,
        )

    async def _execute_locked(self, command: DroneCommand) -> None:
        logger.info("cmd_execute id=%s type=%s", command.command_id, command.type)
        if command.type == CommandType.TAKEOFF:
            await self._preflight_takeoff()
            await self.adapter.takeoff()
            self._watchdog_emergency_sent = False
            return
        if command.type == CommandType.LAND:
            if not await self._is_flying():
                logger.warning("cmd_noop id=%s type=%s reason=not_flying", command.command_id, command.type)
                return
            await self.adapter.land()
            return
        if command.type == CommandType.EMERGENCY:
            await self.adapter.emergency()
            return
        if command.type == CommandType.HOVER:
            if not await self._is_flying():
                logger.warning("cmd_noop id=%s type=%s reason=not_flying", command.command_id, command.type)
                return
            await self.adapter.hover()
            return
        if command.type == CommandType.RC_CONTROL:
            if not await self._is_flying():
                raise RuntimeError("cannot rc_control while not flying")
            assert command.payload is not None
            raw_duration = command.payload.duration_ms
            duration_ms = min(raw_duration, self.config.max_rc_duration_ms)
            if duration_ms != raw_duration:
                logger.info("cmd_duration_clamp original=%d clamped=%d", raw_duration, duration_ms)
            ttl_ms = command.ttl_ms or self.config.default_ttl_ms
            if duration_ms > ttl_ms:
                raise ValueError("rc_control duration_ms cannot exceed command ttl_ms")
            lr = self._clamp_log("left_right", command.payload.left_right)
            fb = self._clamp_log("forward_back", command.payload.forward_back)
            ud = self._clamp_log("up_down", command.payload.up_down)
            yaw = self._clamp_log("yaw", command.payload.yaw)
            await self.adapter.rc_control(lr, fb, ud, yaw)
            await asyncio.sleep(duration_ms / 1000)
            await self.adapter.hover()
            return
        if command.type == CommandType.FLIP:
            if not await self._is_flying():
                raise RuntimeError("cannot flip while not flying")
            state = await self.adapter.get_state()
            if state.battery is not None and state.battery < 50:
                raise RuntimeError(
                    f"refusing flip: battery {state.battery}% is below 50% minimum"
                )
            assert command.payload is not None
            await self.adapter.flip(command.payload.direction)
            return
        raise ValueError(f"unsupported command type {command.type}")

    async def _is_flying(self) -> bool:
        state = await self.adapter.get_state()
        return bool(state.flying)

    async def _preflight_takeoff(self) -> None:
        state = await self.adapter.get_state()
        if not state.connected:
            raise RuntimeError("refusing takeoff: drone is not connected")
        if state.flying:
            return
        if state.battery is None:
            raise RuntimeError("refusing takeoff: battery telemetry unavailable")
        if state.battery < self.config.min_takeoff_battery:
            raise RuntimeError(
                f"refusing takeoff: battery {state.battery}% is below "
                f"{self.config.min_takeoff_battery}% minimum"
            )

    def _clamp(self, value: int) -> int:
        limit = self.config.max_abs_velocity
        return max(-limit, min(limit, value))

    def _clamp_log(self, axis: str, value: int) -> int:
        clamped = self._clamp(value)
        if clamped != value:
            logger.info("cmd_clamp axis=%s original=%d clamped=%d", axis, value, clamped)
        return clamped

    async def _watchdog_loop(self) -> None:
        while not self._closed:
            await asyncio.sleep(self.config.watchdog_interval_s)
            try:
                telemetry = await self.telemetry()
                await self.bus.publish("drone.telemetry", telemetry)

                now = monotonic()
                if not self._lock.locked():
                    async with self._lock:
                        emergency_reasons = self._critical_attitude_reasons(telemetry)
                        if emergency_reasons and not self._watchdog_emergency_sent:
                            await self.adapter.emergency()
                            self._watchdog_emergency_sent = True
                            self._last_command_at = monotonic()
                            await self.bus.publish(
                                "drone.command_results",
                                CommandResult(
                                    command_id="watchdog_emergency",
                                    status=CommandStatus.EXECUTED,
                                    reason="critical attitude: " + ", ".join(emergency_reasons),
                                ),
                            )
                            continue

                        if telemetry.flying and now - self._last_command_at > self.config.stale_command_s:
                            await self.adapter.hover()
                            self._last_command_at = monotonic()

                        if (
                            telemetry.connected
                            and telemetry.flying
                            and now - self._last_keepalive_at > self.config.keepalive_interval_s
                        ):
                            await self.adapter.keepalive()
                            self._last_keepalive_at = monotonic()
            except Exception as exc:
                await self.bus.publish(
                    "drone.command_results",
                    CommandResult(
                        command_id="watchdog",
                        status=CommandStatus.FAILED,
                        reason=str(exc),
                    ),
                )
                if self.config.land_on_adapter_error:
                    try:
                        await self.adapter.land()
                    except Exception:
                        pass

    def _critical_attitude_reasons(self, telemetry: DroneTelemetry) -> list[str]:
        if not telemetry.connected or not telemetry.flying:
            return []
        limit = max(1, self.config.critical_attitude_deg)
        reasons: list[str] = []
        pitch = _float_or_none(telemetry.raw.get("pitch"))
        roll = _float_or_none(telemetry.raw.get("roll"))
        if pitch is not None and abs(pitch) >= limit:
            reasons.append(f"pitch={pitch:g}")
        if roll is not None and abs(roll) >= limit:
            reasons.append(f"roll={roll:g}")
        return reasons


def _float_or_none(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
