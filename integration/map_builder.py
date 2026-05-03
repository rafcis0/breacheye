from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai.depth_log_map import build_point_cloud, write_point_cloud_json
from breacheye.runlog import RunLogger


def main() -> None:
    parser = argparse.ArgumentParser(description="Continuously build a lightweight 3D point-cloud artifact from Rafa depth logs.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--interval-s", type=float, default=1.0)
    parser.add_argument("--stride", type=int, default=18)
    parser.add_argument("--max-frames", type=int, default=24)
    args = parser.parse_args()

    run_dir = Path(args.log_dir).expanduser() / args.run_id
    depth_dir = run_dir / "rafa" / "depth_raw"
    output_dir = run_dir / "map"
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = RunLogger("map_builder", log_dir=args.log_dir, run_id=args.run_id)
    logger.event(
        "map_builder_start",
        depth_dir=depth_dir,
        output_dir=output_dir,
        interval_s=args.interval_s,
        stride=args.stride,
        max_frames=args.max_frames,
    )
    last_points = 0

    while True:
        try:
            points, stats = build_point_cloud(depth_dir=depth_dir, stride=args.stride, max_frames=args.max_frames)
            if stats["points"] != last_points:
                write_point_cloud_json(output_dir / "relative-depth-point-cloud.json", points, source="depth_anything_relative_live")
                write_point_cloud_json(output_dir / "point-cloud.json", points, source="depth_anything_relative_live")
                (output_dir / "live-depth-summary.json").write_text(
                    json.dumps({"run_id": args.run_id, **stats}, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                logger.event(
                    "map_updated",
                    source="depth_anything_relative_live",
                    stats=stats,
                    point_cloud_json=output_dir / "point-cloud.json",
                )
                print(f"map points={stats['points']} frames={stats['frames_used']}", flush=True)
                last_points = stats["points"]
        except FileNotFoundError:
            pass
        except ValueError:
            pass
        except Exception as exc:
            logger.event("map_builder_warning", error=str(exc))
            print(f"map_builder warning: {exc}", flush=True)
        time.sleep(max(1.0, args.interval_s))


if __name__ == "__main__":
    main()
