from pathlib import Path

import numpy as np

from integration.frame_publisher import video_frames


def test_video_frames_support_start_and_stride(tmp_path: Path) -> None:
    import cv2

    path = tmp_path / "sample.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (16, 16))
    try:
        for index in range(20):
            frame = np.full((16, 16, 3), index * 10, dtype=np.uint8)
            writer.write(frame)
    finally:
        writer.release()

    frames = video_frames(path, start_s=1.0, stride=3)
    first = next(frames)
    second = next(frames)

    assert int(first.mean()) >= 80
    assert int(second.mean()) > int(first.mean())
