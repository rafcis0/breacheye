from __future__ import annotations

import logging
import os
from time import time

logger = logging.getLogger(__name__)

from breacheye.rafa.schemas import (
    BBox2D,
    DepthOutput,
    DetectionOutput,
    DoorwayCenteringHint,
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


CLEARANCE_PRESETS: dict[str, float] = {
    "tight": 0.25,    # Small rooms, tight corridors
    "normal": 0.45,   # Default — typical indoor spaces
    "wide": 0.65,     # Open areas, conservative flight
}


def resolve_clearance_threshold(explicit_value: float | None = None) -> float:
    """Resolve clearance threshold from explicit value, preset, or env var.

    Priority: explicit_value > BREACHEYE_NAV_CLEARANCE_PRESET > BREACHEYE_NAV_MIN_FORWARD_CLEARANCE_M > 0.45
    """
    if explicit_value is not None:
        return max(0.0, min(1.0, explicit_value))

    preset = os.environ.get("BREACHEYE_NAV_CLEARANCE_PRESET", "").lower()
    if preset in CLEARANCE_PRESETS:
        return CLEARANCE_PRESETS[preset]

    try:
        value = float(os.environ.get("BREACHEYE_NAV_MIN_FORWARD_CLEARANCE_M", 0.45))
    except (TypeError, ValueError):
        value = 0.45
    return max(0.0, min(1.0, value))


class AdaptiveThreshold:
    """Adjusts clearance threshold based on recent depth statistics."""

    def __init__(self, window_size: int = 30, hysteresis: int = 5) -> None:
        self._window_size = window_size
        self._hysteresis = hysteresis
        self._base_threshold = resolve_clearance_threshold()
        self._current = self._base_threshold
        self._medians: list[float] = []
        self._consecutive_agreement: int = 0
        self._pending_preset: str | None = None

    @property
    def threshold(self) -> float:
        return self._current

    def update(self, depth: DepthOutput) -> float:
        """Feed a depth frame, return current threshold."""
        import numpy as np

        try:
            values = np.frombuffer(depth.depth_bytes, dtype=np.float32).reshape(depth.shape)
            finite = values[np.isfinite(values)]
            if finite.size == 0:
                return self._current
            median = float(np.median(finite))
        except Exception:
            return self._current

        self._medians.append(median)
        if len(self._medians) > self._window_size:
            self._medians = self._medians[-self._window_size:]

        # Determine suggested preset based on rolling median
        rolling_median = sum(self._medians) / len(self._medians)
        if rolling_median < 0.3:
            suggested = "tight"
        elif rolling_median > 0.6:
            suggested = "wide"
        else:
            suggested = "normal"

        # Hysteresis: require N consecutive frames agreeing before switching
        if suggested == self._pending_preset:
            self._consecutive_agreement += 1
        else:
            self._pending_preset = suggested
            self._consecutive_agreement = 1

        if self._consecutive_agreement >= self._hysteresis:
            self._current = CLEARANCE_PRESETS[suggested]

        return self._current


def render_depth_zones(depth: DepthOutput, threshold: float = 0.45) -> bytes:
    """Render depth frame with colored zone overlay. Returns JPEG bytes."""
    import cv2
    import numpy as np

    values = np.frombuffer(depth.depth_bytes, dtype=np.float32).reshape(depth.shape)
    height, width = values.shape

    # Normalize depth to 0-255 grayscale
    valid = values[np.isfinite(values)]
    if valid.size == 0:
        gray = np.zeros((height, width), dtype=np.uint8)
    else:
        normalized = np.clip((values - valid.min()) / max(valid.max() - valid.min(), 1e-6), 0, 1)
        gray = (normalized * 255).astype(np.uint8)

    # Convert to BGR for overlay
    viz = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    # Color overlay per zone
    margin = 0.1  # yellow band width
    zones = {
        "left": (slice(None), slice(0, width // 3)),
        "center": (slice(None), slice(width // 3, (width * 2) // 3)),
        "right": (slice(None), slice((width * 2) // 3, width)),
    }

    for name, (row_slice, col_slice) in zones.items():
        zone_values = values[row_slice, col_slice]
        finite = zone_values[np.isfinite(zone_values)]
        if finite.size == 0:
            continue
        score = float(np.nanpercentile(finite, 20))

        # Create overlay color
        overlay = viz[row_slice, col_slice].copy()
        if score < threshold:
            # Red — blocked
            overlay[:, :, 2] = np.clip(overlay[:, :, 2].astype(int) + 80, 0, 255).astype(np.uint8)
        elif score < threshold + margin:
            # Yellow — marginal
            overlay[:, :, 1] = np.clip(overlay[:, :, 1].astype(int) + 60, 0, 255).astype(np.uint8)
            overlay[:, :, 2] = np.clip(overlay[:, :, 2].astype(int) + 60, 0, 255).astype(np.uint8)
        else:
            # Green — clear
            overlay[:, :, 1] = np.clip(overlay[:, :, 1].astype(int) + 60, 0, 255).astype(np.uint8)
        viz[row_slice, col_slice] = overlay

    # Draw zone boundary lines
    cv2.line(viz, (width // 3, 0), (width // 3, height), (255, 255, 255), 1)
    cv2.line(viz, ((width * 2) // 3, 0), ((width * 2) // 3, height), (255, 255, 255), 1)

    # Add threshold text
    cv2.putText(viz, f"threshold: {threshold:.2f}", (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)

    _, jpeg = cv2.imencode(".jpg", viz, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return jpeg.tobytes()


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
        logger.warning("build_obstacle_alert failed — returning unknown clearance", exc_info=True)
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


def compute_doorway_centering_hints(
    *,
    meta: FrameInput,
    detections: DetectionOutput,
    depth: DepthOutput | None,
    threshold: float = 0.15,
) -> list[DoorwayCenteringHint]:
    """Return centering hints for T1-01 doorway detections.

    Offset is normalized to the visible frame: -1 is far left, +1 is far right,
    and 0 is centered. Depth remains the existing relative contract: 0 near,
    1 far.
    """
    if not meta.width:
        return []
    hints: list[DoorwayCenteringHint] = []
    for detection in detections.detections:
        if detection.category != "T1-01":
            continue
        offset = _bbox_center_offset_ratio(detection.bbox_2d, meta.width)
        centered = abs(offset) <= threshold
        if centered:
            action = "hover"
        elif offset < 0:
            action = "rotate_left"
        else:
            action = "rotate_right"
        hints.append(
            DoorwayCenteringHint(
                frame_id=meta.frame_id,
                doorway_detection_id=detection.id,
                offset_ratio=offset,
                centered=centered,
                approach_depth=_bbox_depth(depth, detection.bbox_2d, meta.width, meta.height),
                suggested_action=action,
                threshold=threshold,
            )
        )
    return hints


def _bbox_center_offset_ratio(bbox: BBox2D, width: int) -> float:
    frame_half = max(width / 2.0, 1.0)
    doorway_center = (bbox.x1 + bbox.x2) / 2.0
    return max(-1.0, min(1.0, (doorway_center - frame_half) / frame_half))


def _bbox_depth(depth: DepthOutput | None, bbox: BBox2D, frame_width: int, frame_height: int | None) -> float | None:
    if depth is None or not frame_width or not frame_height:
        return None
    try:
        import numpy as np

        values = np.frombuffer(depth.depth_bytes, dtype=np.float32).reshape(depth.shape)
        depth_height, depth_width = values.shape
        x1 = int(max(0, min(depth_width - 1, bbox.x1 / frame_width * depth_width)))
        x2 = int(max(0, min(depth_width, bbox.x2 / frame_width * depth_width)))
        y1 = int(max(0, min(depth_height - 1, bbox.y1 / frame_height * depth_height)))
        y2 = int(max(0, min(depth_height, bbox.y2 / frame_height * depth_height)))
        if x2 <= x1 or y2 <= y1:
            return None

        # Doorframe edges are often close. Sample the inner region so the
        # approach score better reflects the opening itself.
        width = x2 - x1
        height = y2 - y1
        inner_x1 = x1 + max(0, int(width * 0.25))
        inner_x2 = x2 - max(0, int(width * 0.25))
        inner_y1 = y1 + max(0, int(height * 0.25))
        inner_y2 = y2 - max(0, int(height * 0.15))
        region = values[inner_y1:max(inner_y1 + 1, inner_y2), inner_x1:max(inner_x1 + 1, inner_x2)]
        finite = region[np.isfinite(region)]
        if not finite.size:
            return None
        return float(np.nanpercentile(finite, 50))
    except Exception:
        return None


def _resolve_frontier_clearance(value: float | None) -> float:
    return resolve_clearance_threshold(value)


def compute_obstacle_alert(
    depth: DepthOutput,
    frame_id: int,
    threshold: float = 0.45,
) -> ObstacleAlert:
    """Compute per-zone proximity scores from depth output."""
    import numpy as np

    values = np.frombuffer(depth.depth_bytes, dtype=np.float32).reshape(depth.shape)
    height, width = values.shape

    # Split into left/center/right thirds (column-wise)
    left_zone = values[:, : width // 3]
    center_zone = values[:, width // 3 : (width * 2) // 3]
    right_zone = values[:, (width * 2) // 3 :]

    zones = {}
    for name, zone in [("left", left_zone), ("center", center_zone), ("right", right_zone)]:
        finite = zone[np.isfinite(zone)]
        if finite.size:
            zones[name] = float(np.nanpercentile(finite, 20))
        else:
            zones[name] = 1.0  # no data = assume clear

    nearest = min(zones.values())
    blocked = any(v < threshold for v in zones.values())

    return ObstacleAlert(
        frame_id=frame_id,
        nearest_obstacle_m=nearest,
        zones=zones,
        blocked=blocked,
        threshold=threshold,
    )
