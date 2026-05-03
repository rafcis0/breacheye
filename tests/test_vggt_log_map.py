from pathlib import Path

import numpy as np
import pytest

from ai.vggt_log_map import select_frames, write_point_cloud_json


def test_select_frames_uses_stride_and_limit(tmp_path: Path) -> None:
    frame_dir = tmp_path / "frames"
    frame_dir.mkdir()
    for index in range(8):
        (frame_dir / f"frame-{index:08d}.jpg").write_bytes(b"jpg")

    frames = select_frames(frame_dir, max_frames=3, stride=2)

    assert [path.name for path in frames] == [
        "frame-00000000.jpg",
        "frame-00000002.jpg",
        "frame-00000004.jpg",
    ]


def test_select_frames_raises_without_frames(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        select_frames(tmp_path, max_frames=3, stride=1)


def test_write_point_cloud_json_normalizes_points(tmp_path: Path) -> None:
    path = tmp_path / "point-cloud.json"
    points = np.array([[0, 0, 0], [10, 5, 2]], dtype=np.float32)

    write_point_cloud_json(path, points, source="test")

    text = path.read_text(encoding="utf-8")
    assert '"source":"test"' in text
    assert '"points"' in text
