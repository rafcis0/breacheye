from pathlib import Path
import runpy

import numpy as np

from ai.depth_log_map import build_point_cloud


def test_map_builder_depth_inputs_are_compatible(tmp_path: Path) -> None:
    depth_dir = tmp_path / "rafa" / "depth_raw"
    depth_dir.mkdir(parents=True)
    np.save(depth_dir / "frame-00000001.npy", np.ones((6, 6), dtype=np.float32))

    points, stats = build_point_cloud(depth_dir, stride=3, max_frames=1)

    assert points.shape[1] == 4
    assert stats["points"] == 4


def test_map_builder_script_imports() -> None:
    globals_after_load = runpy.run_path("integration/map_builder.py", run_name="map_builder_test")

    assert "main" in globals_after_load
