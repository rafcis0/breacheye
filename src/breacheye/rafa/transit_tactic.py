from __future__ import annotations

from dataclasses import dataclass
from time import time

from breacheye.rafa.schemas import (
    DetectionOutput,
    DoorwayCenteringHint,
    NavigationDecision,
    NavigationOutput,
    SpatialNavigationContext,
)


@dataclass
class TransitTacticResult:
    output: NavigationOutput | None
    event: dict | None = None


@dataclass
class TransitTactic:
    """Doorway transit override for centered T1-01 detections.

    This stays deliberately small and stateful. It bypasses VLM navigation only
    while crossing a confirmed doorway, then hands control back to normal node
    search after a short clearing pulse.
    """

    centering_threshold: float = 0.15
    approach_depth_threshold: float = 0.30
    abort_depth_threshold: float = 0.16
    approach_steps: int = 2
    pass_steps: int = 3
    clearing_steps: int = 1

    phase: str = "idle"
    doorway_detection_id: str | None = None
    transit_id: int = 0
    phase_step: int = 0

    def decide(
        self,
        *,
        detections: DetectionOutput,
        context: SpatialNavigationContext,
    ) -> TransitTacticResult:
        hint = self._best_hint(detections)
        if self.phase == "idle":
            if hint is None:
                return TransitTacticResult(output=None)
            self._start(hint)
            if not hint.centered:
                return self._centering_output(hint)
            self._set_phase("approaching")
            return self._approach_output(detections.frame_id, hint)

        if self._unexpected_close_obstacle(context):
            return self._abort(detections.frame_id, "unexpected close obstacle in transit path")

        if self.phase == "centering":
            if hint is None:
                return self._abort(detections.frame_id, "doorway lost during centering")
            if not hint.centered:
                return self._centering_output(hint)
            self._set_phase("approaching")
            return self._approach_output(detections.frame_id, hint)

        if self.phase == "approaching":
            if hint is not None and not hint.centered:
                self._set_phase("centering")
                return self._centering_output(hint)
            if self._close_enough(hint) or self.phase_step >= self.approach_steps:
                self._set_phase("passing_through")
                return self._passing_output(detections.frame_id, hint)
            return self._approach_output(detections.frame_id, hint)

        if self.phase == "passing_through":
            if self.phase_step >= self.pass_steps:
                self._set_phase("clearing")
                return self._clearing_output(detections.frame_id)
            return self._passing_output(detections.frame_id, hint)

        if self.phase == "clearing":
            if self.phase_step >= self.clearing_steps:
                return self._complete(detections.frame_id)
            return self._clearing_output(detections.frame_id)

        return self._abort(detections.frame_id, f"unknown transit phase {self.phase!r}")

    def _best_hint(self, detections: DetectionOutput) -> DoorwayCenteringHint | None:
        if not detections.doorway_centering_hints:
            return None
        return min(detections.doorway_centering_hints, key=lambda hint: abs(hint.offset_ratio))

    def _start(self, hint: DoorwayCenteringHint) -> None:
        self.transit_id += 1
        self.doorway_detection_id = hint.doorway_detection_id
        self._set_phase("centering")

    def _set_phase(self, phase: str) -> None:
        if self.phase != phase:
            self.phase = phase
            self.phase_step = 0

    def _centering_output(self, hint: DoorwayCenteringHint) -> TransitTacticResult:
        degrees = max(5, min(20, int(abs(hint.offset_ratio) * 30)))
        action = hint.suggested_action if hint.suggested_action != "hover" else "hover"
        params = {"degrees": degrees, "transit_phase": "centering", "doorway_detection_id": hint.doorway_detection_id}
        output = NavigationOutput(
            frame_id=hint.frame_id,
            decision=NavigationDecision(
                action=action,
                params=params,
                confidence=0.82,
                reasoning=(
                    "Doorway transit: centering on T1-01 doorway "
                    f"{hint.doorway_detection_id} offset={hint.offset_ratio:.3f}."
                ),
                exploration_state="doorway_centering",
            ),
        )
        event = self._event("centering", hint.frame_id, status="active", hint=hint)
        return TransitTacticResult(output=output, event=event)

    def _approach_output(self, frame_id: int, hint: DoorwayCenteringHint | None) -> TransitTacticResult:
        self.phase_step += 1
        output = NavigationOutput(
            frame_id=frame_id,
            decision=NavigationDecision(
                action="move_forward",
                params={
                    "distance_cm": 20,
                    "speed_cm_s": 15,
                    "transit_phase": "approaching",
                    "doorway_detection_id": self.doorway_detection_id or "",
                },
                confidence=0.78,
                reasoning="Doorway transit: approaching centered doorway at reduced speed.",
                exploration_state="doorway_approaching",
            ),
        )
        event = self._event("approaching", frame_id, status="active", hint=hint)
        return TransitTacticResult(output=output, event=event)

    def _passing_output(self, frame_id: int, hint: DoorwayCenteringHint | None) -> TransitTacticResult:
        self.phase_step += 1
        output = NavigationOutput(
            frame_id=frame_id,
            decision=NavigationDecision(
                action="move_forward",
                params={
                    "distance_cm": 25,
                    "speed_cm_s": 18,
                    "transit_phase": "passing_through",
                    "relax_depth_guard": 1,
                    "doorway_detection_id": self.doorway_detection_id or "",
                },
                confidence=0.74,
                reasoning="Doorway transit: passing through doorframe with relaxed side-depth guard.",
                exploration_state="doorway_passing_through",
            ),
        )
        event = self._event("passing_through", frame_id, status="active", hint=hint)
        return TransitTacticResult(output=output, event=event)

    def _clearing_output(self, frame_id: int) -> TransitTacticResult:
        self.phase_step += 1
        output = NavigationOutput(
            frame_id=frame_id,
            decision=NavigationDecision(
                action="move_forward",
                params={
                    "distance_cm": 15,
                    "speed_cm_s": 15,
                    "transit_phase": "clearing",
                    "doorway_detection_id": self.doorway_detection_id or "",
                },
                confidence=0.7,
                reasoning="Doorway transit: clearing the threshold before resuming exploration.",
                exploration_state="doorway_clearing",
            ),
        )
        event = self._event("clearing", frame_id, status="active")
        return TransitTacticResult(output=output, event=event)

    def _complete(self, frame_id: int) -> TransitTacticResult:
        doorway_id = self.doorway_detection_id or "unknown-doorway"
        event = self._event("resumed", frame_id, status="completed")
        self._reset()
        output = NavigationOutput(
            frame_id=frame_id,
            decision=NavigationDecision(
                action="hover",
                params={"duration_ms": 250, "transit_phase": "resumed", "doorway_detection_id": doorway_id},
                confidence=0.7,
                reasoning="Doorway transit complete; establishing new room node.",
                exploration_state="doorway_resumed",
            ),
        )
        return TransitTacticResult(output=output, event=event)

    def _abort(self, frame_id: int, reason: str) -> TransitTacticResult:
        event = self._event("aborted", frame_id, status="aborted", reason=reason)
        self._reset()
        output = NavigationOutput(
            frame_id=frame_id,
            decision=NavigationDecision(
                action="hover",
                params={"duration_ms": 500, "transit_phase": "aborted"},
                confidence=0.8,
                reasoning=f"Doorway transit aborted: {reason}.",
                exploration_state="doorway_aborted",
            ),
        )
        return TransitTacticResult(output=output, event=event)

    def _reset(self) -> None:
        self.phase = "idle"
        self.doorway_detection_id = None
        self.phase_step = 0

    def _close_enough(self, hint: DoorwayCenteringHint | None) -> bool:
        return hint is not None and hint.approach_depth is not None and hint.approach_depth <= self.approach_depth_threshold

    def _unexpected_close_obstacle(self, context: SpatialNavigationContext) -> bool:
        nearest = context.looking_at.nearest_obstacle_m
        return nearest is not None and nearest <= self.abort_depth_threshold

    def _event(
        self,
        phase: str,
        frame_id: int,
        *,
        status: str,
        hint: DoorwayCenteringHint | None = None,
        reason: str | None = None,
    ) -> dict:
        return {
            "transit_id": self.transit_id,
            "phase": phase,
            "status": status,
            "frame_id": frame_id,
            "doorway_detection_id": self.doorway_detection_id,
            "phase_step": self.phase_step,
            "offset_ratio": hint.offset_ratio if hint is not None else None,
            "centered": hint.centered if hint is not None else None,
            "approach_depth": hint.approach_depth if hint is not None else None,
            "reason": reason,
            "timestamp": time(),
        }
