import json

from breacheye.rafa.orchestrator import RafaPipeline, RafaPipelineConfig
from breacheye.rafa.schemas import (
    LookingAt,
    MapFrontier,
    NavigationDecision,
    NavigationOutput,
    SpatialNavigationContext,
)


def test_navigation_safety_override_blocks_forward_when_depth_is_close(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BREACHEYE_NAV_MIN_FORWARD_CLEARANCE_M", "0.35")
    pipeline = RafaPipeline(RafaPipelineConfig(log_dir=str(tmp_path), run_id="safety"))
    output = NavigationOutput(
        frame_id=22,
        decision=NavigationDecision(
            action="move_forward",
            params={"speed_cm_s": 20},
            confidence=0.91,
            reasoning="open hallway ahead",
        ),
    )
    context = SpatialNavigationContext(
        frame_id=22,
        looking_at=LookingAt(direction_label="forward", nearest_obstacle_m=0.1),
        unexplored_frontiers=[],
    )

    guarded = pipeline._apply_navigation_safety_override(output, context)

    assert guarded.decision.action == "rotate_right"
    assert guarded.decision.exploration_state == "obstacle_avoidance"
    events = [json.loads(line) for line in (tmp_path / "safety-rafa.jsonl").read_text().splitlines()]
    override_events = [event for event in events if event["event"] == "navigation_safety_override"]
    assert override_events
    assert override_events[-1]["requested_action"] == "move_forward"
    assert override_events[-1]["substituted_action"] == "rotate_right"


def test_navigation_safety_override_allows_forward_when_frontier_is_clear(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BREACHEYE_NAV_MIN_FORWARD_CLEARANCE_M", "0.35")
    pipeline = RafaPipeline(RafaPipelineConfig(log_dir=str(tmp_path), run_id="safety"))
    output = NavigationOutput(
        frame_id=17,
        decision=NavigationDecision(
            action="move_forward",
            params={"speed_cm_s": 20},
            confidence=0.9,
            reasoning="frontier ahead",
        ),
    )
    context = SpatialNavigationContext(
        frame_id=17,
        looking_at=LookingAt(direction_label="forward", nearest_obstacle_m=0.77),
        unexplored_frontiers=[MapFrontier(id="frontier-17", bearing_deg=0, label="open forward view")],
    )

    guarded = pipeline._apply_navigation_safety_override(output, context)

    assert guarded == output
