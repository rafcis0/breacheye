import json

import numpy as np

from ai.depth_log_map import build_point_cloud, main


def test_build_point_cloud_from_logged_depth_arrays(tmp_path) -> None:
    depth_dir = tmp_path / "run" / "rafa" / "depth_raw"
    depth_dir.mkdir(parents=True)
    np.save(depth_dir / "frame-00000000.npy", np.arange(16, dtype=np.float32).reshape(4, 4))

    points, stats = build_point_cloud(depth_dir, stride=2, max_frames=1)

    assert points.shape == (4, 4)
    assert stats["frames_used"] == 1
    assert stats["points"] == 4


def test_depth_log_map_cli_writes_ply_and_summary(tmp_path, monkeypatch, capsys) -> None:
    depth_dir = tmp_path / "logs" / "map-test" / "rafa" / "depth_raw"
    depth_dir.mkdir(parents=True)
    np.save(depth_dir / "frame-00000000.npy", np.ones((4, 4), dtype=np.float32))
    monkeypatch.setattr(
        "sys.argv",
        [
            "depth_log_map",
            "--run-id",
            "map-test",
            "--log-dir",
            str(tmp_path / "logs"),
            "--stride",
            "2",
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["points"] == 4
    assert (tmp_path / "logs" / "map-test" / "map" / "relative-depth-point-cloud.ply").exists()
    assert (tmp_path / "logs" / "map-test" / "map" / "relative-depth-summary.json").exists()
