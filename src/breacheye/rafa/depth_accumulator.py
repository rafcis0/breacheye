from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any


@dataclass(frozen=True)
class DepthSample:
    frame_id: int
    timestamp: float
    yaw_deg: float
    min_depth: float
    mean_depth: float
    center_depth: float
    shape: tuple[int, int]


@dataclass
class DepthAccumulator:
    """Rolling depth summary used by reporting and map/debug views."""

    max_samples: int = 120
    samples: list[DepthSample] = field(default_factory=list)

    def add_sample(
        self,
        *,
        frame_id: int,
        timestamp: float | None,
        yaw_deg: float,
        depth_array: Any,
    ) -> DepthSample:
        import numpy as np

        values = np.asarray(depth_array, dtype=np.float32)
        if values.ndim != 2:
            raise ValueError("depth_array must be a 2D array")

        finite = values[np.isfinite(values)]
        if finite.size:
            min_depth = float(np.nanmin(finite))
            mean_depth = float(np.nanmean(finite))
        else:
            min_depth = 1.0
            mean_depth = 1.0

        height, width = values.shape
        center = values[height // 3 : (height * 2) // 3, width // 3 : (width * 2) // 3]
        center_finite = center[np.isfinite(center)]
        center_depth = float(np.nanmean(center_finite)) if center_finite.size else mean_depth

        sample = DepthSample(
            frame_id=frame_id,
            timestamp=timestamp if timestamp is not None else time(),
            yaw_deg=yaw_deg,
            min_depth=_clamp01(min_depth),
            mean_depth=_clamp01(mean_depth),
            center_depth=_clamp01(center_depth),
            shape=(int(height), int(width)),
        )
        self.samples.append(sample)
        if len(self.samples) > self.max_samples:
            self.samples = self.samples[-self.max_samples :]
        return sample

    def latest(self) -> DepthSample | None:
        return self.samples[-1] if self.samples else None

    def model_dump(self) -> dict:
        return {
            "max_samples": self.max_samples,
            "sample_count": len(self.samples),
            "latest": _sample_dump(self.latest()),
            "samples": [_sample_dump(sample) for sample in self.samples],
        }


def _sample_dump(sample: DepthSample | None) -> dict | None:
    if sample is None:
        return None
    return {
        "frame_id": sample.frame_id,
        "timestamp": sample.timestamp,
        "yaw_deg": sample.yaw_deg,
        "min_depth": sample.min_depth,
        "mean_depth": sample.mean_depth,
        "center_depth": sample.center_depth,
        "shape": sample.shape,
    }


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value
