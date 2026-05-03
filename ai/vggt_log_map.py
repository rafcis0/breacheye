from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a VGGT-MPS point-cloud artifact from logged flight frames.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--vggt-root", type=Path, default=Path("vggt-mps"))
    parser.add_argument("--checkpoint", type=Path, default=Path("~/Downloads/model.pt"))
    parser.add_argument("--max-frames", type=int, default=12)
    parser.add_argument("--stride", type=int, default=2, help="Use every Nth logged frame.")
    parser.add_argument("--point-step", type=int, default=8, help="Point-cloud downsample step.")
    args = parser.parse_args()

    run_dir = Path(args.log_dir).expanduser() / args.run_id
    frame_dir = run_dir / "rafa" / "frames"
    output_dir = run_dir / "map"
    output_dir.mkdir(parents=True, exist_ok=True)

    frames = select_frames(frame_dir, max_frames=args.max_frames, stride=args.stride)
    points = run_vggt(
        frames,
        vggt_root=args.vggt_root.expanduser(),
        checkpoint=args.checkpoint.expanduser(),
        point_step=args.point_step,
    )
    artifact = output_dir / "vggt-point-cloud.json"
    write_point_cloud_json(artifact, points, source="vggt_mps")
    write_point_cloud_json(output_dir / "point-cloud.json", points, source="vggt_mps")
    summary = {
        "run_id": args.run_id,
        "frames_used": len(frames),
        "points": int(points.shape[0]),
        "output": str(artifact),
        "checkpoint": str(args.checkpoint.expanduser()),
        "vggt_root": str(args.vggt_root.expanduser()),
    }
    (output_dir / "vggt-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))


def select_frames(frame_dir: Path, max_frames: int, stride: int) -> list[Path]:
    files = sorted(frame_dir.glob("frame-*.jpg"))
    if not files:
        raise FileNotFoundError(f"no logged frames found in {frame_dir}")
    stride = max(1, stride)
    selected = files[::stride][:max_frames]
    if not selected:
        raise FileNotFoundError(f"no frames selected from {frame_dir}")
    return selected


def run_vggt(frames: list[Path], vggt_root: Path, checkpoint: Path, point_step: int) -> np.ndarray:
    if not vggt_root.exists():
        raise FileNotFoundError(f"VGGT-MPS checkout not found: {vggt_root}")
    if not checkpoint.exists():
        raise FileNotFoundError(f"VGGT checkpoint not found: {checkpoint}")

    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    sys.path.insert(0, str(vggt_root / "src"))
    sys.path.insert(0, str(vggt_root / "repo" / "vggt"))
    from vggt_mps.vggt_core import VGGTProcessor

    processor = VGGTProcessor(device="mps")
    processor.load_model(checkpoint)
    images = [np.array(Image.open(path).convert("RGB")) for path in frames]
    result = processor.process_images(images)
    if isinstance(result, dict) and result.get("depth_maps") is not None:
        points = _points_from_depth_with_colors(images, result["depth_maps"], point_step=point_step)
    elif isinstance(result, dict) and result.get("point_cloud") is not None:
        points = np.asarray(result["point_cloud"], dtype=np.float32)
    elif isinstance(result, list):
        points = _points_from_depth_with_colors(images, result, point_step=point_step)
    else:
        raise RuntimeError("VGGT-MPS did not return point-cloud or depth outputs")
    if points.ndim != 2 or points.shape[1] < 3:
        raise RuntimeError(f"invalid point cloud shape from VGGT-MPS: {points.shape}")
    return points


def _points_from_depth_with_colors(images: list[np.ndarray], depth_maps: list[np.ndarray], point_step: int) -> np.ndarray:
    all_points = []
    step = max(1, point_step)
    for index, (image, depth) in enumerate(zip(images, depth_maps, strict=False)):
        height, width = depth.shape
        if image.shape[0] != height or image.shape[1] != width:
            image = np.array(Image.fromarray(image).resize((width, height)))
        fx = fy = 500.0
        cx = width / 2.0
        cy = height / 2.0
        yy, xx = np.mgrid[0:height:step, 0:width:step]
        z = depth[::step, ::step].astype(np.float32)
        x = ((xx.astype(np.float32) - cx) * z / fx) + index * 2.0
        y = (yy.astype(np.float32) - cy) * z / fy
        colors = image[::step, ::step, :3].astype(np.float32) / 255.0
        all_points.append(
            np.stack(
                [
                    x.reshape(-1),
                    y.reshape(-1),
                    z.reshape(-1),
                    colors[:, :, 0].reshape(-1),
                    colors[:, :, 1].reshape(-1),
                    colors[:, :, 2].reshape(-1),
                ],
                axis=1,
            )
        )
    return np.concatenate(all_points, axis=0).astype(np.float32)


def write_point_cloud_json(path: Path, points: np.ndarray, source: str) -> None:
    max_points = 12000
    finite = np.isfinite(points[:, :3]).all(axis=1)
    sampled = points[finite]
    if sampled.shape[0] > max_points:
        indices = np.linspace(0, sampled.shape[0] - 1, max_points).astype(np.int64)
        sampled = sampled[indices]
    mins = sampled.min(axis=0) if sampled.size else np.zeros(3, dtype=np.float32)
    maxs = sampled.max(axis=0) if sampled.size else np.ones(3, dtype=np.float32)
    center = (mins + maxs) / 2.0
    scale = max(float((maxs - mins).max()), 1e-6)
    normalized = (sampled - center) / scale
    payload = {
        "type": "point_cloud",
        "source": source,
        "points": [
            _point_payload(normalized[index], sampled[index])
            for index in range(normalized.shape[0])
        ],
    }
    path.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")


def _point_payload(position: np.ndarray, source_row: np.ndarray) -> dict:
    payload = {
        "x": float(position[0]),
        "y": float(position[1]),
        "z": float(position[2]),
        "intensity": 0.8,
    }
    if source_row.shape[0] >= 6:
        payload["r"] = float(np.clip(source_row[3], 0.0, 1.0))
        payload["g"] = float(np.clip(source_row[4], 0.0, 1.0))
        payload["b"] = float(np.clip(source_row[5], 0.0, 1.0))
    return payload


if __name__ == "__main__":
    main()
