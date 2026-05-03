from __future__ import annotations

from dataclasses import dataclass, field
from time import time

from breacheye.rafa.schemas import NavigationDecision, NavigationOutput, SpatialNavigationContext


@dataclass
class SearchTacticResult:
    output: NavigationOutput
    event: dict | None = None


@dataclass
class NodeSearchTactic:
    """Small local exploration tactic until real SLAM pose/frontiers are wired.

    A node is the current hover position. Headings are relative yaw slots from
    that position. The tactic marks the current slot open/blocked from the
    current-frame spatial context, rotates when blocked, and starts a fresh node
    when it allows a forward move.
    """

    clearance_threshold: float
    scan_degrees: int = 20
    node_id: int = 0
    heading_index: int = 0
    heading_status: dict[int, str] = field(default_factory=dict)

    def apply(self, output: NavigationOutput, context: SpatialNavigationContext) -> SearchTacticResult:
        decision = output.decision
        blocked = self._is_blocked(context)
        self.heading_status[self.heading_index] = "blocked" if blocked else "open"

        if decision.action == "move_forward" and not blocked:
            event = self._event(
                "advance",
                decision,
                context,
                blocked=blocked,
                substituted_action=decision.action,
            )
            self._advance_node()
            return SearchTacticResult(output=output, event=event)

        if blocked and decision.action == "hover":
            event = self._event(
                "hold_blocked_heading",
                decision,
                context,
                blocked=blocked,
                substituted_action=decision.action,
            )
            return SearchTacticResult(output=output, event=event)

        if blocked and decision.action not in {"land", "rotate_left", "rotate_right"}:
            guarded = NavigationOutput(
                frame_id=output.frame_id,
                timestamp=output.timestamp,
                decision=NavigationDecision(
                    action="rotate_right",
                    params={"degrees": self.scan_degrees},
                    confidence=min(decision.confidence, 0.7),
                    reasoning=(
                        "Node search: current heading is blocked; rotating to sample the next heading. "
                        f"Requested {decision.action}: {decision.reasoning}"
                    ),
                    exploration_state="obstacle_avoidance",
                ),
            )
            event = self._event(
                "scan_blocked_heading",
                decision,
                context,
                blocked=blocked,
                substituted_action=guarded.decision.action,
            )
            self._advance_heading(1)
            return SearchTacticResult(output=guarded, event=event)

        if decision.action == "rotate_right":
            event = self._event(
                "scan_requested",
                decision,
                context,
                blocked=blocked,
                substituted_action=decision.action,
            )
            self._advance_heading(1)
            return SearchTacticResult(output=output, event=event)

        if decision.action == "rotate_left":
            event = self._event(
                "scan_requested",
                decision,
                context,
                blocked=blocked,
                substituted_action=decision.action,
            )
            self._advance_heading(-1)
            return SearchTacticResult(output=output, event=event)

        return SearchTacticResult(output=output)

    def _is_blocked(self, context: SpatialNavigationContext) -> bool:
        nearest = context.looking_at.nearest_obstacle_m
        blocked_by_depth = nearest is not None and nearest <= self.clearance_threshold
        no_forward_frontier = not context.unexplored_frontiers
        return blocked_by_depth or no_forward_frontier

    def _advance_heading(self, delta: int) -> None:
        self.heading_index = (self.heading_index + delta) % max(1, round(360 / self.scan_degrees))

    def _advance_node(self) -> None:
        self.node_id += 1
        self.heading_index = 0
        self.heading_status.clear()

    def reset_for_new_room(self) -> None:
        self._advance_node()

    def _event(
        self,
        reason: str,
        decision: NavigationDecision,
        context: SpatialNavigationContext,
        *,
        blocked: bool,
        substituted_action: str,
    ) -> dict:
        return {
            "reason": reason,
            "node_id": self.node_id,
            "heading_index": self.heading_index,
            "heading_deg": self.heading_index * self.scan_degrees,
            "scan_degrees": self.scan_degrees,
            "blocked": blocked,
            "requested_action": decision.action,
            "substituted_action": substituted_action,
            "nearest_obstacle_m": context.looking_at.nearest_obstacle_m,
            "min_forward_clearance_m": self.clearance_threshold,
            "frontier_count": len(context.unexplored_frontiers),
            "heading_status": dict(sorted(self.heading_status.items())),
            "timestamp": time(),
        }
