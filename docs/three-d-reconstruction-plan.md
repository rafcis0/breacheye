# 3D Reconstruction Plan

3D reconstruction should be a mapping artifact, not the dependency for safe flight. The flight loop should stay simple: frame -> perception/depth -> nav decision -> safety harness. 3D can run in parallel and lag behind.

## Practical Demo Path

For the hackathon demo, build in this order:

1. **Pose-lite path from commands**
   - Integrate Cooper's executed nav commands into a dead-reckoned local pose.
   - `move_forward 30cm` updates local `x/y`.
   - `rotate_right 20deg` updates yaw.
   - Good enough for a live tactical sketch.

2. **Depth-backed point hints**
   - Use Rafa depth output to project sparse points from keyframes.
   - Depth is relative, so treat this as qualitative room geometry until calibrated.
   - Publish local-frame POI positions as approximate.

3. **POI map**
   - Attach detections to the current pose/yaw and show them in a local 2D/2.5D map.
   - This is more demo-reliable than full dense reconstruction.

4. **Offline reconstruction**
   - Save frames and pose estimates to `logs/`/ignored capture folders.
   - Run COLMAP/SfM or Gaussian/NeRF tooling offline after the flight if time allows.

## Why Not Dense 3D First

The Tello gives monocular video, not metric depth or reliable onboard pose. Dense 3D needs enough baseline, texture, camera calibration, and stable pose. It is valuable, but it can consume the demo if we make it a gating dependency.

## Recommended Near-Term Interface

Add a local map event stream on a new ZMQ output port after the current Cooper/Rafa contract is stable:

```json
{
  "frame_id": 42,
  "pose": {"x_m": 1.2, "y_m": 0.4, "z_m": 0.8, "yaw_deg": 35},
  "pois": [
    {"id": "det-042-001", "category": "T1-01", "x_m": 1.6, "y_m": 0.8, "confidence": 0.87}
  ]
}
```

Cooper can render this as a 2D tactical map now. Rafa can later add sparse point clouds or meshes behind the same pose/POI concept.

## Logging Requirements

Every map event should also be written into the same run-scoped JSONL logs as frames, detections, depth, navigation, and health. During Tello Wi-Fi runs we may lose internet/debugger access, so reconstruction must be reproducible after the fact from:

- frame ids and timestamps
- accepted nav commands
- Tello state samples
- depth summaries
- POI detections
- emitted map events

## Current First Pass Is Not A Building Map

The current report map is only a debug artifact. It stacks relative depth samples from independent frames, so it can show whether depth outputs are nonblank, but it does not estimate camera pose, align frames into one coordinate system, reconstruct walls, or locate people/doors in the actual building.

The FlyMeThrough-style system we need is different:

1. Extract RGB keyframes from drone video.
2. Estimate camera extrinsics/trajectory with SfM or SLAM.
3. Reconstruct sparse/dense geometry from posed images.
4. Segment people, doors, stairs, hazards, and user-defined POIs across frames.
5. Project masks/detections into the reconstructed 3D coordinate system.
6. Review the semantic 3D map in the report/UI.

The FlyMeThrough paper used RGB video, extracted frames at `2 FPS`, estimated camera extrinsics, reconstructed the space with SfM/photogrammetry, then used SAM2-assisted human annotation and depth-guided raycasting to place POIs into the 3D map. Their evaluation also notes a practical issue we should expect: open-source COLMAP-style SfM can drift in large/repetitive indoor spaces, while a commercial photogrammetry tool was more robust for their tested building-scale scans.

## Debug Depth Artifact

Rafa writes both human and numeric depth artifacts:

```text
logs/<run_id>/rafa/depth/frame-XXXXXXXX.png
logs/<run_id>/rafa/depth_raw/frame-XXXXXXXX.npy
```

The PNG is for quick inspection. The `.npy` file is the relative `float32` depth array used by post-run mapping.

Create a first-pass relative point cloud from a run:

```bash
python ai/depth_log_map.py --run-id "$BREACHEYE_RUN_ID" --log-dir logs --stride 12 --max-frames 20
```

Outputs:

```text
logs/<run_id>/map/relative-depth-point-cloud.ply
logs/<run_id>/map/point-cloud.json
logs/<run_id>/map/relative-depth-summary.json
```

`point-cloud.json` is served by the harness at `/map/point-cloud/latest` and rendered by the frontend 3D panel. This is not metric reconstruction. It stacks relative monocular depth slices into a rough point cloud so we can see whether the depth stream is stable enough to justify heavier SLAM/SfM work.

VGGT-MPS checkpoint path once `~/Downloads/model.pt` finishes:

```bash
python ai/vggt_log_map.py \
  --run-id "$BREACHEYE_RUN_ID" \
  --log-dir logs \
  --vggt-root vggt-mps \
  --checkpoint ~/Downloads/model.pt \
  --max-frames 12 \
  --stride 2
```

This writes:

```text
logs/<run_id>/map/vggt-point-cloud.json
logs/<run_id>/map/point-cloud.json
logs/<run_id>/map/vggt-summary.json
```

The live frontend polls `/map/point-cloud/latest`, so the 3D render updates automatically when either the relative-depth mapper or VGGT-MPS writes a new artifact.

## Reconstruction Workspace

Prepare a true reconstruction workspace from a video segment:

```bash
python ai/reconstruction_prep.py \
  --video /Users/rafael/Downloads/drone_mock.mp4 \
  --run-id "$BREACHEYE_RUN_ID" \
  --log-dir logs \
  --start-s 125 \
  --fps 2
```

Outputs:

```text
logs/<run_id>/reconstruction/images/frame-000000.jpg
logs/<run_id>/reconstruction/manifest.json
```

If COLMAP is installed, inspect or run the open-source SfM pass:

```bash
python ai/reconstruction_colmap.py --workspace logs/<run_id>/reconstruction --dry-run
python ai/reconstruction_colmap.py --workspace logs/<run_id>/reconstruction
```

COLMAP is not currently installed on this Mac, so the committed script is a repeatable integration point rather than a completed reconstruction result.

## Better Later

- Camera calibration for Tello intrinsics.
- Visual odometry or SLAM (`ORB-SLAM`, `OpenVINS`, `COLMAP`, `MAST3R-SLAM` offline).
- SAM2/Grounded-SAM style mask propagation for people, doors, stairs, and hazards.
- Raycast segmentation masks into the SfM/SLAM map to create semantic 3D POIs.
- Depth Anything V2 metric-ish calibration against known Tello movement increments.
- Export point cloud/mesh for the UI or Foundry attachment.
