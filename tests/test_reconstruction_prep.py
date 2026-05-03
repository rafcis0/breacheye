from pathlib import Path

import numpy as np

from ai.reconstruction_colmap import build_colmap_commands
from ai.reconstruction_prep import extract_video_frames


def test_extract_video_frames_writes_manifest_and_images(tmp_path: Path) -> None:
    import cv2

    video = tmp_path / "room.mp4"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 10, (32, 24))
    try:
        for index in range(30):
            writer.write(np.full((24, 32, 3), index * 5, dtype=np.uint8))
    finally:
        writer.release()

    manifest = extract_video_frames(
        video=video,
        workspace=tmp_path / "reconstruction",
        start_s=1.0,
        fps=2.0,
        max_frames=3,
    )

    assert manifest["frame_count"] == 3
    assert (tmp_path / "reconstruction" / "manifest.json").exists()
    assert len(list((tmp_path / "reconstruction" / "images").glob("*.jpg"))) == 3
    assert manifest["frames"][0]["source_timestamp_s"] >= 1.0


def test_colmap_commands_target_workspace(tmp_path: Path) -> None:
    commands = build_colmap_commands(tmp_path / "reconstruction")

    assert commands[0][0] == "colmap"
    assert "feature_extractor" in commands[0]
    assert "sequential_matcher" in commands[1]
    assert "mapper" in commands[2]
