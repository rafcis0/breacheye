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
        band = values[height // 3 : (height * 2) // 3, width // 3 : (width * 2) // 3]
        if not band.size:
            return None
        finite = band[np.isfinite(band)]
        if not finite.size:
            return None
        # Depth Anything output is relative, so this is a normalized proximity hint, not meters.
        # Use the center-band median instead of the absolute minimum so noisy pixels or a
        # small near object do not incorrectly close an otherwise open forward frontier.
        return float(np.nanpercentile(finite, 50))
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
            value = float(os.environ.get("BREACHEYE_NAV_MIN_FORWARD_CLEARANCE_M", 0.35))
        except (TypeError, ValueError):
            value = 0.35
    return max(0.0, min(10.0, value))
