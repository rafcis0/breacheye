from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an open-source COLMAP SfM pass on prepared reconstruction frames.")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--camera-model", default="SIMPLE_RADIAL")
    parser.add_argument("--single-camera", action="store_true", default=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    commands = build_colmap_commands(args.workspace, camera_model=args.camera_model, single_camera=args.single_camera)
    if args.dry_run:
        print(json.dumps({"commands": commands}, indent=2))
        return
    run_colmap(commands)


def build_colmap_commands(workspace: Path, camera_model: str = "SIMPLE_RADIAL", single_camera: bool = True) -> list[list[str]]:
    images = workspace / "images"
    database = workspace / "colmap" / "database.db"
    sparse = workspace / "colmap" / "sparse"
    database.parent.mkdir(parents=True, exist_ok=True)
    sparse.mkdir(parents=True, exist_ok=True)
    return [
        [
            "colmap",
            "feature_extractor",
            "--database_path",
            str(database),
            "--image_path",
            str(images),
            "--ImageReader.camera_model",
            camera_model,
            "--ImageReader.single_camera",
            "1" if single_camera else "0",
        ],
        [
            "colmap",
            "sequential_matcher",
            "--database_path",
            str(database),
        ],
        [
            "colmap",
            "mapper",
            "--database_path",
            str(database),
            "--image_path",
            str(images),
            "--output_path",
            str(sparse),
        ],
    ]


def run_colmap(commands: list[list[str]]) -> None:
    if shutil.which("colmap") is None:
        raise SystemExit("COLMAP is not installed. Install COLMAP or run with --dry-run to inspect commands.")
    for command in commands:
        subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
