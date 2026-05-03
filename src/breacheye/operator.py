from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from breacheye.bus import AsyncEventBus
from breacheye.state_machine import FlightStateMachine


class OperatorAction(StrEnum):
    ABORT = "abort"
    PAUSE = "pause"
    RESUME = "resume"


class OperatorCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: OperatorAction
    issued_by: str = "operator"


class OperatorHandler:
    def __init__(self, fsm: FlightStateMachine, bus: AsyncEventBus) -> None:
        self._fsm = fsm
        self._bus = bus

    async def handle(self, command: OperatorCommand) -> dict:
        """Execute operator command. Returns result dict."""
        if command.action == OperatorAction.ABORT:
            await self._fsm.abort()
            return {"action": "abort", "state": str(self._fsm.state), "success": True}
        elif command.action == OperatorAction.PAUSE:
            await self._fsm.pause()
            return {"action": "pause", "paused": self._fsm.paused, "success": True}
        elif command.action == OperatorAction.RESUME:
            await self._fsm.resume()
            return {"action": "resume", "paused": self._fsm.paused, "success": True}
        else:
            return {"action": str(command.action), "success": False, "reason": "unknown action"}
