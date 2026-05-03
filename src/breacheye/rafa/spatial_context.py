from __future__ import annotations

import os

from breacheye.rafa.schemas import (
    DepthOutput,
    DetectionOutput,
    FrameInput,
    LookingAt,
    MapFrontier,
    MapObject,
    MapPose,
    NavigationAction,
    SpatialNavigationContext,
)


def build_spatial_context(
    *,
    meta: FrameInput,
    detections: DetectionOutput,
    depth: DepthOutput | None,
    recent_actions: list[NavigationAction],
    frontier_clearance: float | None = None,
) -> SpatialNavigationContext:
    clearance = _resolve_frontier_clearance(frontier_clearance)
    nearest = _nearest_center_depth(depth)
    objects = [
        MapObject(
            id=detection.id,
            type=detection.label,
            relative_position=_bbox_relative_position(detection.bbox_2d.x1, detection.bbox_2d.x2, meta.width),
            confidence=detection.confidence,
        )
        for detection in detections.detections
    ]
    frontiers: list[MapFrontier] = []
    if nearest is None or nearest > clearance:
        frontiers.append(
            MapFrontier(
                id=f"frontier-{meta.frame_id:06d}-forward",
                bearing_deg=0.0,
                distance_m=None,
                label="open forward view",
            )
        )
    return SpatialNavigationContext(
        frame_id=meta.frame_id,
        current_pose=MapPose(source="unavailable"),
        looking_at=LookingAt(
            direction_label="forward",
            nearest_obstacle_m=nearest,
            visible_region="current_camera_frame",
        ),
        visited=[],
        unexplored_frontiers=frontiers,
        known_objects=objects,
        recent_actions=recent_actions[-8:],
        source="stub_from_current_frame",
    )


def summarize_spatial_context(context: SpatialNavigationContext) -> dict:
    return {
        "frame_id": context.frame_id,
        "pose_source": context.current_pose.source,
        "nearest_obstacle_m": context.looking_at.nearest_obstacle_m,
        "frontiers": len(context.unexplored_frontiers),
        "known_objects": len(context.known_objects),
        "recent_actions": context.recent_actions,
        "source": context.source,
    }


def _nearest_center_depth(depth: DepthOutput | None) -> float | None:
    if depth is None:
        return None
    try:
        import numpy as np

        values = np.frombuffer(depth.depth_bytes, dtype=np.float32).reshape(depth.shape)
        height, width = values.shape
        center_band = values[height // 3 : (height * 2) // 3, width // 3 : (width * 2) // 3]
        lower_forward = values[
            int(height * 0.45) : int(height * 0.9),
            int(width * 0.25) : int(width * 0.75),
        ]
        if not center_band.size and not lower_forward.size:
            return None
        scores = []
        center_finite = center_band[np.isfinite(center_band)]
        if center_finite.size:
            scores.append(float(np.nanpercentile(center_finite, 50)))
        lower_finite = lower_forward[np.isfinite(lower_forward)]
        if lower_finite.size:
            scores.append(float(np.nanpercentile(lower_finite, 20)))
        if not scores:
            return None
        # This is a normalized forward-clearance hint, not metric depth. The
        # lower-forward band catches close objects in the actual flight path.
        return min(scores)
    except Exception:
        return None


def _bbox_relative_position(x1: int, x2: int, width: int | None) -> str:
    if not width:
        return "unknown"
    center = (x1 + x2) / 2
    if center < width / 3:
        return "left"
    if center > (width * 2) / 3:
        return "right"
    return "center"


def _resolve_frontier_clearance(value: float | None) -> float:
    if value is None:
        try:
            value = float(os.environ.get("BREACHEYE_NAV_MIN_FORWARD_CLEARANCE_M", 0.45))
        except (TypeError, ValueError):
            value = 0.45
    return max(0.0, min(10.0, value))
