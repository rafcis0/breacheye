# 3D Viewer Feature Spec

**Status:** Scoped, not started
**Date:** 2026-05-02
**Scoped by:** Garrus (architecture), Shepard (PM)

## Summary

Upgrade the working 2D tactical system to include a post-flight 3D reconstruction with POI annotations rendered in a BabylonJS viewer. This is a stretch feature — the 2D system is complete and functional without it.

## Recommended Approach: Layered Hybrid

Pre-computed mesh loaded into BabylonJS with live POI overlay projected from dead-reckoned poses. If COLMAP validates on Tello footage, swap in the real mesh. If it fails, a pre-baked mesh still delivers the demo visual.

**The sell:** "After the drone completes its sweep, we reconstruct the space in 3D and place all tactical POIs in their precise spatial locations."

### Why This Approach

- **Not pure batch COLMAP:** 720p Tello footage is unvalidated for COLMAP. If feature extraction fails (motion blur, low texture), you have nothing for the demo.
- **Not pure real-time:** Dead-reckoned depth point clouds look rough — scattered points without surface continuity.
- **Hybrid wins:** Visual impact of a mesh (even if pre-baked) plus live intelligence layer (POI markers). Whether the mesh was built 10 minutes ago or during a practice run is invisible to judges.

### Critical Insight

Skip dense reconstruction entirely. COLMAP's colored sparse point cloud can be loaded directly into BabylonJS as a "3D scan." This avoids the CUDA-blocked dense stereo step completely and still reads as impressive.

## Work Breakdown

### Backend (Alpha track, ~4h)

| ID | Task | Hours | Depends On |
|----|------|-------|------------|
| B1 | Validate COLMAP on Tello footage | 1.0 | Practice flight footage |
| B2 | Mesh/PLY export from COLMAP sparse output | 1.0 | B1 success |
| B3 | POI-to-3D coordinate projection (pinhole model) | 1.5 | Detection pipeline output |
| B4 | Serve mesh + POI JSON via HTTP or static `public/` | 0.5 | B2 or B5 |
| B5 | Fallback mesh (iPhone LiDAR scan or sample OBJ) | 0.5 | None (insurance) |

### Frontend (Beta track, ~3.5h)

| ID | Task | Hours | Depends On |
|----|------|-------|------------|
| F1 | BabylonJS viewer component (from reference code) | 1.5 | None |
| F2 | POI overlay in 3D space (wireframe bboxes, category colors) | 1.0 | B3 format spec |
| F3 | Integration into existing React layout | 0.5 | F1 + F2 |
| F4 | Loading states and polish | 0.5 | F3 |

### Total: ~8h work, ~5h critical path

Backend and frontend are fully parallelizable.

## Critical Path

```
B1 (validate COLMAP) ──┬── SUCCESS ──> B2 (export) ──> B4 (serve) ─┐
                       │                                            │
                       └── FAIL ────> B5 (fallback) ──> B4 ────────┘
                                                                    ├─> Final integration
F1 (BabylonJS component) ──> F2 (POI overlay) ──> F3 (layout) ────┘

B3 (POI projection) runs independent, feeds F2
```

## Decision Gate

**B1: COLMAP validation on Tello footage.**
- Success metric: >60% of images registered in sparse reconstruction
- If pass: real mesh path (impressive)
- If fail: pre-baked fallback (still good demo)

Start B1 immediately with whatever practice footage exists. This is the gate.

## Technical Details

### Backend: POI Projection (B3)

Simple pinhole camera model — skip the heavyweight raycasting from `function_cast.py`.

```
pixel (u, v) + depth_value + camera_pose → world_coordinate (x, y, z)

Tello intrinsics (estimated):
- Resolution: 960x720
- FOV: ~82 degrees
- fx/fy: ~550px
- cx/cy: 480/360
```

Output JSON format (matching reference viewer):
```json
{
  "object_id": {
    "bounding_boxes": [{"obb_corners": [...]}],
    "description": "T1-01 Person",
    "category": "T1-01"
  }
}
```

### Frontend: BabylonJS Viewer (F1)

Based on reference code at `~/tacticalscan-ref/reference-code/frontend-viewer/BabylonScene.js` (942 lines).

Simplified for hackathon:
- Single scene (no dual-view)
- ArcRotateCamera with arrow key navigation
- OBJ/PLY loader
- Dark tactical theme (black background, match existing UI)
- Category-colored wireframe bounding boxes for POIs

### Backend: COLMAP Pipeline (B1/B2)

```bash
# Existing scripts
python ai/reconstruction_prep.py --video <footage> --fps 2
python ai/reconstruction_colmap.py --workspace logs/<run_id>/reconstruction

# GLOMAP mode (10-50x faster than incremental)
colmap automatic_reconstructor --mapper GLOBAL ...

# Export sparse point cloud as PLY (skip dense entirely)
colmap model_converter --input_path sparse/0 --output_path model.ply --output_type PLY
```

## Hardware Constraints

- Mac 36GB Apple Silicon (MPS). No CUDA.
- COLMAP sparse SfM: works on CPU (use `--SiftExtraction.use_gpu 0`)
- COLMAP dense stereo: BLOCKED (hard-requires CUDA)
- Dense alternatives: OpenMVS CPU-only (slow, 10-20 min), OpenSplat Gaussian Splatting (Metal native)
- Recommended: skip dense, use sparse PLY directly

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| COLMAP fails on 720p Tello (motion blur, low texture) | 40% | Medium | B5 fallback mesh |
| Dead-reckoned pose drift misaligns POIs | 50% | Low | Roughly right is good enough for demo |
| BabylonJS bundle size (3MB+) | 10% | Low | Lazy load viewer component |
| Tello intrinsics inaccurate without calibration | 25% | Medium | Validate with 1-2 known objects |

## Reference Materials

| File | Purpose |
|------|---------|
| `~/breacheye/docs/three-d-reconstruction-plan.md` | Rafa's approach doc |
| `~/breacheye/ai/reconstruction_colmap.py` | COLMAP pipeline scaffold |
| `~/breacheye/ai/reconstruction_prep.py` | Frame extraction |
| `~/breacheye/ai/depth_log_map.py` | Depth-to-point-cloud |
| `~/tacticalscan-ref/reference-code/frontend-viewer/BabylonScene.js` | 942-line BabylonJS reference |
| `~/tacticalscan-ref/reference-code/servers/function_cast.py` | Raycasting (skip for hackathon) |
| `~/tacticalscan-ref/research/technology/08_sfm-alternatives.md` | COLMAP/GLOMAP evaluation |
| `~/tacticalscan-ref/research/technology/24_apple-silicon-solutions.md` | Mac-viable dense paths |

## Session Assignments (when ready)

- **Alpha:** B1, B2, B3, B4 (backend reconstruction + serving)
- **Beta:** F1, F2, F3, F4 (frontend BabylonJS viewer)
- **B5** (fallback mesh): whoever has 30 min free, or pre-demo insurance

## Next Steps (when resuming)

1. Create GitHub issues for B1-B5, F1-F4
2. Start B1 + F1 in parallel (Alpha + Beta)
3. B1 result determines real vs fallback mesh path
4. Agree on POI JSON format contract before B3/F2 start
