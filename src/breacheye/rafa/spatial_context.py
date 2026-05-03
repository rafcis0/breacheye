from __future__ import annotations

import os
from time import time

from breacheye.rafa.schemas import (
    DepthOutput,
    DetectionOutput,
    FrameInput,
    LookingAt,
    MapFrontier,
    MapObject,
    MapPose,
    NavigationAction,
    ObstacleAlert,
    ObstacleDirection,
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
    alert = build_obstacle_alert(depth, frame_ts=meta.timestamp) if depth is not None else None
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
        obstacle_alert=alert,
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


_OBSTACLE_THRESHOLD = 0.15


def build_obstacle_alert(
    depth: DepthOutput,
    *,
    threshold: float = _OBSTACLE_THRESHOLD,
    frame_ts: float | None = None,
) -> ObstacleAlert:
    """Compute an ObstacleAlert from a depth map.

    Depth values are in relative 0-near/1-far space. An obstacle is detected
    when the nearest forward-region depth falls below *threshold* (default 0.15).
    Direction hint is determined by comparing per-column-third medians.
    Clearance score is the clamped inverse of obstacle proximity (1.0 = fully
    clear, 0.0 = obstacle at sensor minimum).
    """
    try:
        import numpy as np

        values = np.frombuffer(depth.depth_bytes, dtype=np.float32).reshape(depth.shape)
        height, width = values.shape

        # Center band used for mean_center_depth
        center_rows = values[height // 3 : (height * 2) // 3, width // 3 : (width * 2) // 3]
        center_finite = center_rows[np.isfinite(center_rows)]
        mean_center = float(np.nanmean(center_finite)) if center_finite.size else 1.0

        # Forward region: lower-center strip captures the actual flight path
        forward = values[
            int(height * 0.45) : int(height * 0.9),
            int(width * 0.25) : int(width * 0.75),
        ]
        forward_finite = forward[np.isfinite(forward)]
        min_depth = float(np.nanmin(forward_finite)) if forward_finite.size else 1.0

        obstacle_detected = min_depth < threshold

        # Direction: compare 2nd-percentile of left / center / right thirds of forward region
        fw_h, fw_w = forward.shape
        col_third = fw_w // 3
        def _region_min(region: "np.ndarray") -> float:  # type: ignore[type-arg]
            finite = region[np.isfinite(region)]
            return float(np.nanpercentile(finite, 2)) if finite.size else 1.0

        left_min = _region_min(forward[:, :col_third])
        center_min = _region_min(forward[:, col_third : col_third * 2])
        right_min = _region_min(forward[:, col_third * 2 :])

        direction: ObstacleDirection
        if obstacle_detected:
            closest = min(left_min, center_min, right_min)
            if closest == center_min:
                direction = "center"
            elif closest == left_min:
                direction = "left"
            else:
                direction = "right"
        else:
            direction = "unknown"

        clearance_score = float(np.clip((min_depth - threshold) / max(1.0 - threshold, 1e-6), 0.0, 1.0))
        return ObstacleAlert(
            frame_id=depth.frame_id,
            timestamp=frame_ts if frame_ts is not None else time(),
            min_depth=float(np.clip(min_depth, 0.0, 1.0)),
            mean_center_depth=float(np.clip(mean_center, 0.0, 1.0)),
            obstacle_detected=obstacle_detected,
            direction_hint=direction,
            clearance_score=clearance_score,
        )
    except Exception:
        return ObstacleAlert(
            frame_id=depth.frame_id,
            timestamp=frame_ts if frame_ts is not None else time(),
            min_depth=1.0,
            mean_center_depth=1.0,
            obstacle_detected=False,
            direction_hint="unknown",
            clearance_score=1.0,
        )


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
