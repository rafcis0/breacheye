# BreachEye Constitution

The binding interface contract between tracks. Changes require agreement from both Rafa (AI/ML) and Cooper (Integration).

Reference: [WORKPLAN.md](WORKPLAN.md) for schedule and task breakdown.

## Tracks

- **Rafa (AI/ML):** Model inference, detection, depth, navigation decisions. Produces JSON on ZMQ channels.
- **Cooper (Integration):** Drone control, state machine, Palantir AIP, frontend. Consumes JSON, issues commands.

## Transport: ZMQ Pub/Sub on Localhost

| Channel | Port | Publisher | Subscriber | Format |
|---------|------|-----------|------------|--------|
| frames | 5555 | Cooper | Rafa | msgpack: {frame_id, timestamp, jpeg_bytes} |
| detections | 5556 | Rafa | Cooper | JSON (see Detection Contract) |
| depth | 5557 | Rafa | Cooper | msgpack: {frame_id, depth_bytes, shape} |
| navigation | 5558 | Rafa | Cooper | JSON (see Navigation Contract) |
| health | 5559 | Rafa | Cooper | JSON (see Health Contract) |

## Frame Input Contract (resolves #1)

Cooper produces, Rafa consumes. Wire format is JPEG bytes with metadata, not raw numpy.

```json
{
  "frame_id": 42,
  "timestamp": 1746201234.567,
  "width": 960,
  "height": 720,
  "encoding": "jpeg_bgr_source",
  "jpeg_bytes": "<msgpack bin>"
}
```

- Wire: msgpack on ZMQ port 5555. `jpeg_bytes` is required.
- Source: BGR (OpenCV default from djitellopy), JPEG-compressed for transport.
- Rafa decodes to BGR numpy locally: `cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8), cv2.IMREAD_COLOR)`
- Do NOT resize before passing — Rafa's pipeline handles model preprocessing.
- Decode failures logged, not fatal.

## Detection Output Contract

Rafa produces, Cooper consumes.

```json
{
  "frame_id": 42,
  "timestamp": 1746201234.567,
  "detections": [
    {
      "id": "det-042-001",
      "category": "T1-01",
      "label": "Entry Point",
      "description": "Wooden door, appears unlocked",
      "confidence": 0.87,
      "bbox_2d": {"x1": 120, "y1": 80, "x2": 340, "y2": 520},
      "threat_level": "CLEAR",
      "detection_model": "moondream"
    }
  ],
  "processing_ms": 23
}
```

## POI Categories

| Code | Label | Color |
|------|-------|-------|
| T1-01 | Entry/Exit Point | #60a5fa |
| T1-02 | Fatal Funnel | #f87171 |
| T1-03 | Stairs/Vertical | #818cf8 |
| T2-02 | Threat Indicator | #f87171 |
| T2-03 | Chokepoint | #fbbf24 |
| T3-01 | Utility Panel | #a78bfa |
| T4-01 | Structural Damage | #fb923c |
| ROOM | Room/Open Area | #2dd4bf |

## Threat Levels

`HOT` | `WARM` | `CAUTION` | `CLEAR` | `INFO`

## Depth Output Contract (resolves #2)

Wire format is raw float32 bytes with explicit metadata via msgpack on port 5557.

```json
{
  "frame_id": 42,
  "timestamp": 1746201234.567,
  "shape": [720, 960],
  "dtype": "float32",
  "unit": "relative_0_near_1_far",
  "depth_bytes": "<msgpack bin, raw float32>"
}
```

- Consumer reconstructs: `np.frombuffer(depth_bytes, dtype=np.float32).reshape(shape)`
- NOT metric. Obstacle avoidance threshold: ~0.15 for "close".
- If depth unavailable: Rafa publishes health error, nav fallback avoids forward movement.

## Navigation Decision Contract (resolves #3)

Rafa publishes high-level semantic actions, not RC velocity commands. Cooper maps to djitellopy. Confidence below 0.5 is treated as `hover`.

```json
{
  "frame_id": 42,
  "timestamp": 1746201234.567,
  "decision": {
    "action": "move_forward",
    "params": {"distance_cm": 50, "speed_cm_s": 30},
    "confidence": 0.82,
    "reasoning": "Open corridor ahead, no obstacles within 2m",
    "exploration_state": "exploring"
  }
}
```

### Valid Actions

| Action | Params | djitellopy | Default Distance/Angle |
|--------|--------|------------|------------------------|
| move_forward | distance_cm | tello.move_forward() | 30-50 cm |
| move_back | distance_cm | tello.move_back() | 30-50 cm |
| move_left | distance_cm | tello.move_left() | 30-50 cm |
| move_right | distance_cm | tello.move_right() | 30-50 cm |
| move_up | distance_cm | tello.move_up() | 20-30 cm |
| move_down | distance_cm | tello.move_down() | 20-30 cm |
| rotate_left | degrees | tello.rotate_counter_clockwise() | 15-30 deg |
| rotate_right | degrees | tello.rotate_clockwise() | 15-30 deg |
| hover | duration_ms | (no-op) | — |
| land | — | tello.land() | — |

### Exploration States

`exploring` | `investigating_poi` | `returning` | `obstacle_avoidance` | `coverage_complete` | `low_battery`

### Confidence Handling

- confidence >= 0.5: Cooper executes the action.
- confidence < 0.5: Cooper executes `hover`, logs the rejected payload.
- Invalid/malformed JSON: Cooper executes `hover`, logs to health channel.

## Health Contract

```json
{
  "pipeline_status": "ready",
  "models_loaded": {
    "moondream": {"status": "ready", "vram_mb": 1800},
    "depth_anything_v2": {"status": "ready", "vram_mb": 600},
    "qwen3_vl": {"status": "ready", "vram_mb": 4200}
  },
  "throughput": {"detection_fps": 12.5, "depth_fps": 8.3, "decision_fps": 0.7},
  "memory": {"ram_used_gb": 8.4, "vram_total_gb": 36.0}
}
```

## Model Fallback Policy (resolves #4)

Interfaces are frozen. Models are not. Rafa may swap models behind the same ZMQ contracts.

| Layer | Preferred | Fallback 1 | Fallback 2 |
|-------|-----------|------------|------------|
| Detection | Moondream Photon | YOLO-World (same POI JSON) | Rule-based from depth only |
| Depth | Depth Anything V2 | No depth — nav avoids forward, hover/rotate only | — |
| Navigation | Qwen 3-VL 8B | Rule-based from detections + depth | Scripted scan pattern |

Rules:
- Output contracts do not change regardless of model.
- Health channel identifies active model names and fallback state.
- Demo can run in stub/scripted mode if all models fail.

## Schema Validation and Error Handling (resolves #5)

Both sides validate. Different responsibilities.

**Rafa (publisher):** Validate before publish. Retry/repair model JSON locally. Log failures to health channel.

**Cooper (consumer):** Validate on consume. Apply safe fallback behavior:
- Detection malformed: skip frame, publish health error.
- Depth malformed: nav avoids forward movement, publish health error.
- Navigation malformed: execute `hover`, log rejected payload.
- Repeated malformed nav (3+ consecutive): hold hover or land depending on battery/operator.

One bad model response must never crash the live demo.

## Benchmarks

| Component | Target | Acceptable | Failure |
|-----------|--------|------------|---------|
| Moondream/frame | 20ms | 50ms | >100ms |
| Depth/frame | 31ms | 50ms | >100ms |
| Qwen/keyframe | 1.5s | 3s | >5s |
| Frame capture | 30 FPS | 15 FPS | <10 FPS |
| Memory (all models) | 8GB | 12GB | >20GB |

## Alignment Gates

Decide before building. Defaults apply if no discussion.

| # | Decision | Default |
|---|----------|---------|
| 1 | Frame format | BGR numpy, 960x720 |
| 2 | Transport | ZMQ pub/sub |
| 3 | POI categories | 8 codes above |
| 4 | Nav actions | 10 actions above |
| 5 | Keyframe trigger | Every 30 frames |
| 6 | Memory budget | ~7GB models |
| 7 | Palantir push freq | Batch every 5s |
