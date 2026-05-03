from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare RGB video frames for true SfM/semantic reconstruction.")
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--start-s", type=float, default=0.0)
    parser.add_argument("--end-s", type=float)
    parser.add_argument("--fps", type=float, default=2.0, help="Target extracted frame rate. FlyMeThrough used 2 FPS.")
    parser.add_argument("--max-frames", type=int, default=0, help="0 means no cap.")
    args = parser.parse_args()

    workspace = Path(args.log_dir).expanduser() / args.run_id / "reconstruction"
    manifest = extract_video_frames(
        video=args.video,
        workspace=workspace,
        start_s=args.start_s,
        end_s=args.end_s,
        fps=args.fps,
        max_frames=args.max_frames or None,
    )
    print(json.dumps(manifest, sort_keys=True))


def extract_video_frames(
    *,
    video: Path,
    workspace: Path,
    start_s: float = 0.0,
    end_s: float | None = None,
    fps: float = 2.0,
    max_frames: int | None = None,
) -> dict[str, Any]:
    import cv2

    if fps <= 0:
        raise ValueError("fps must be > 0")
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise ValueError(f"failed to open video {video}")

    images_dir = workspace / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    source_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    source_frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration_s = source_frame_count / source_fps if source_fps > 0 and source_frame_count > 0 else None
    if start_s > 0:
        capture.set(cv2.CAP_PROP_POS_MSEC, start_s * 1000)

    interval_s = 1.0 / fps
    next_sample_s = start_s
    frames = []
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            pos_ms = float(capture.get(cv2.CAP_PROP_POS_MSEC) or 0.0)
            timestamp_s = pos_ms / 1000.0
            if end_s is not None and timestamp_s > end_s:
                break
            if timestamp_s + 1e-6 < next_sample_s:
                continue
            frame_index = len(frames)
            name = f"frame-{frame_index:06d}.jpg"
            path = images_dir / name
            if not cv2.imwrite(str(path), frame):
                raise ValueError(f"failed to write {path}")
            height, width = frame.shape[:2]
            frames.append(
                {
                    "index": frame_index,
                    "source_timestamp_s": timestamp_s,
                    "image": str(path.relative_to(workspace)),
                    "width": int(width),
                    "height": int(height),
                }
            )
            next_sample_s = timestamp_s + interval_s
            if max_frames is not None and len(frames) >= max_frames:
                break
    finally:
        capture.release()

    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "source_video": str(video),
        "workspace": str(workspace),
        "images_dir": str(images_dir),
        "start_s": start_s,
        "end_s": end_s,
        "target_fps": fps,
        "source_fps": source_fps,
        "source_frame_count": source_frame_count,
        "source_duration_s": duration_s,
        "frames": frames,
        "frame_count": len(frames),
        "next_stage": "Run SfM/SLAM to estimate camera poses and reconstruct sparse/dense geometry from reconstruction/images.",
    }
    (workspace / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    main()
