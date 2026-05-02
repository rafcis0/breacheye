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

## Current First Pass

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
logs/<run_id>/map/relative-depth-summary.json
```

This is not metric reconstruction. It stacks relative monocular depth slices into a rough point cloud so we can see whether the depth stream is stable enough to justify heavier SLAM/SfM work.

## Better Later

- Camera calibration for Tello intrinsics.
- Visual odometry or SLAM (`ORB-SLAM`, `OpenVINS`, `COLMAP` offline).
- Depth Anything V2 metric-ish calibration against known Tello movement increments.
- Export point cloud/mesh for the UI or Foundry attachment.
