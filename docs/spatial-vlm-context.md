# Spatial VLM Context

Issue: https://github.com/rafcis0/breacheye/issues/49

The navigation VLM should not reason from the current frame alone once reconstruction is available. It needs compact spatial memory: where the drone is, what it is looking at, what has already been seen, where unexplored frontiers are, and where people/doors/hazards/POIs sit in the map.

## Why

Single-frame navigation cannot distinguish:

- an already-seen hallway from a new frontier
- a person behind the drone from a person ahead
- a doorway that leads to unexplored space from a closed dead end
- a safe forward motion from moving into a near obstacle

The map context should stay structured and small. Do not pass point clouds, meshes, or long histories directly to the VLM.

## Context Payload

Initial schema:

```json
{
  "current_pose": {"x": 1.2, "y": 0.4, "z": 0.9, "yaw_deg": 35.0},
  "looking_at": {
    "direction_label": "open doorway",
    "nearest_obstacle_m": 1.8,
    "visible_region": "entry_hall_to_living_room"
  },
  "visited": ["entry_hall", "living_room_left"],
  "unexplored_frontiers": [
    {"id": "frontier_3", "bearing_deg": 12.0, "distance_m": 2.4, "label": "open doorway"}
  ],
  "known_objects": [
    {"id": "person_1", "type": "person", "relative_position": "behind-left", "confidence": 0.82}
  ],
  "recent_actions": ["hover", "move_forward"],
  "allowed_actions": ["hover", "move_forward", "rotate_left", "rotate_right"]
}
```

## Data Sources

- Current frame: Cooper/Rafa JPEG input.
- Current pose and camera frustum: VGGT-MPS or later SfM/SLAM backend.
- Point cloud or mesh: reconstruction output, summarized into frontiers and obstacles.
- Semantic objects: detector/segmentation output projected into map coordinates.
- Action history: safety harness accepted commands, not raw VLM suggestions.

## Logging

The pipeline now logs `navigation_context_built` before every navigation decision. In the current implementation the context source is `stub_from_current_frame`: it summarizes current-frame detections, relative center-depth, and recent accepted actions. Pose is marked `unavailable` until VGGT-MPS or a later reconstruction backend is wired in.

Current depth gating is relative, not metric. `nearest_obstacle_m` is the forward-clearance score from normalized Depth Anything output after conversion to `relative_0_near_1_far`. It combines the center median with a lower-forward near percentile so objects in the flight corridor can close the frontier. The practical block threshold is `BREACHEYE_NAV_MIN_FORWARD_CLEARANCE_M` and defaults to `0.45`; increasing it makes the drone rotate sooner, decreasing it allows tighter forward views.

Until real SLAM pose/frontiers exist, Rafa uses a lightweight node-search tactic:

1. Treat the current hover position as a search node.
2. Treat each yaw sample as a heading on that node.
3. Mark the heading `blocked` when center depth is below the threshold or there is no forward frontier.
4. If blocked, publish a short `rotate_right` and re-assess the next heading.
5. If a forward action is allowed, start a fresh node after that movement.

This is logged as `navigation_search_tactic` with `node_id`, `heading_index`, `heading_status`, `nearest_obstacle_m`, and the substituted action. It is intentionally conservative and should be replaced by VGGT-MPS pose/frontier updates once they are reliable.

Every model-mode navigation decision should eventually log:

```text
navigation_context_built
navigation_context_sent
navigation_raw_model_response
navigation_decision_validated
```

Each event must include `frame_id`, run id, context summary, and artifact paths when available. This is mandatory for Tello Wi-Fi debugging.

## Prompt Shape

The navigator prompt should combine:

1. Current image.
2. Compact map context JSON.
3. Safety/action constraints.
4. Required output schema.

The VLM should choose an allowed action that advances toward unexplored frontiers unless safety, obstacle proximity, or operator policy says to hover/rotate.

## Implementation Order

1. Done: add Pydantic schemas for `SpatialNavigationContext`, `MapPose`, `MapFrontier`, and `MapObject`.
2. Done: add a stub context builder from current frame/action history so tests can land before VGGT-MPS integration.
3. Next: add a VGGT-MPS output reader once local outputs exist.
4. Next: feed context into Qwen server navigator and log raw context/model output.
5. Next: update report to show per-frame camera frustum and context payload.
