from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a first-pass point cloud from logged Rafa depth arrays.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--stride", type=int, default=12)
    parser.add_argument("--max-frames", type=int, default=20)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    run_dir = Path(args.log_dir).expanduser() / args.run_id
    depth_dir = run_dir / "rafa" / "depth_raw"
    output_dir = args.output_dir or run_dir / "map"
    output_dir.mkdir(parents=True, exist_ok=True)

    points, stats = build_point_cloud(depth_dir=depth_dir, stride=args.stride, max_frames=args.max_frames)
    ply_path = output_dir / "relative-depth-point-cloud.ply"
    summary_path = output_dir / "relative-depth-summary.json"
    write_ply(ply_path, points)
    summary = {
        "run_id": args.run_id,
        "depth_dir": str(depth_dir),
        "output": str(ply_path),
        "stride": args.stride,
        "max_frames": args.max_frames,
        **stats,
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))


def build_point_cloud(depth_dir: Path, stride: int = 12, max_frames: int = 20) -> tuple[np.ndarray, dict]:
    files = sorted(depth_dir.glob("frame-*.npy"))[:max_frames]
    if not files:
        raise FileNotFoundError(f"no depth arrays found in {depth_dir}")

    all_points = []
    frame_spacing = 0.35
    for frame_index, path in enumerate(files):
        depth = np.load(path).astype(np.float32)
        finite = np.isfinite(depth)
        if not finite.any():
            continue
        near = float(np.nanpercentile(depth[finite], 2))
        far = float(np.nanpercentile(depth[finite], 98))
        denom = max(far - near, 1e-6)
        normalized = np.clip((depth - near) / denom, 0.0, 1.0)
        height, width = depth.shape
        ys, xs = np.mgrid[0:height:stride, 0:width:stride]
        zs = normalized[ys, xs]
        x_norm = (xs.astype(np.float32) - width / 2) / max(width, 1)
        y_norm = (ys.astype(np.float32) - height / 2) / max(height, 1)
        frame_offset = frame_index * frame_spacing
        points = np.stack(
            [
                x_norm.reshape(-1),
                np.full(xs.size, frame_offset, dtype=np.float32),
                (1.0 - zs).reshape(-1),
                y_norm.reshape(-1),
            ],
            axis=1,
        )
        all_points.append(points)

    if not all_points:
        raise ValueError(f"depth arrays in {depth_dir} contained no finite values")
    combined = np.concatenate(all_points, axis=0)
    stats = {
        "frames_used": len(files),
        "points": int(combined.shape[0]),
        "relative_depth_min": float(combined[:, 2].min()),
        "relative_depth_max": float(combined[:, 2].max()),
    }
    return combined, stats


def write_ply(path: Path, points: np.ndarray) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write("ply\n")
        handle.write("format ascii 1.0\n")
        handle.write(f"element vertex {points.shape[0]}\n")
        handle.write("property float x\n")
        handle.write("property float y\n")
        handle.write("property float z\n")
        handle.write("property float intensity\n")
        handle.write("end_header\n")
        for x, y, z, intensity in points:
            handle.write(f"{x:.6f} {y:.6f} {z:.6f} {intensity:.6f}\n")


if __name__ == "__main__":
    main()
