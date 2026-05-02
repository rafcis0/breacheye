# BreachEye — Hackathon Workplan

## Overview

BreachEye is a VLM-driven autonomous indoor drone mapping system. A DJI Tello flies through a building, a local vision model detects tactical POIs in real time, and all findings are pushed to Palantir AIP for operator-facing common operating picture.

**Team:** Rafa (AI/ML) · Cooper (Integration)
**Hardware:** DJI Tello (720p, 13-min battery) · 36GB Mac (Apple Silicon MPS)
**Architecture:** Dual-loop — inner loop runs on Mac at 50ms target, outer loop pushes to Palantir every 5s

---

## Architecture Diagram

```
INNER LOOP (on Mac, 50ms target):
  Tello 720p → Moondream detect (20ms) → Depth Anything V2 (31ms)
  → State Machine → Qwen 3-VL reasoning (keyframes, 1-2s) → djitellopy

OUTER LOOP (Palantir AIP, 2-5s):
  Batch push → FlightDecision + TacticalPoi → Ontology → Workshop COP
  Operator override → OperatorCommand → Mac polls → state machine
```

---

## Interface Contracts

All contracts are frozen at H+0. Do not change format without notifying the other track.

### Frame Input (Cooper → Rafa)

- Format: BGR numpy array via ZMQ pub on port 5555
- Resolution: 960x720 (Tello native)
- Payload: msgpack `{frame_id: int, timestamp: float, jpeg_bytes: bytes}`

### Detection Output (Rafa → Cooper)

ZMQ pub on port 5556.

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

### POI Category Codes

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

### Depth Output (Rafa → Cooper)

- Format: float32 numpy array (720, 960)
- Unit: relative (0.0 = near, 1.0 = far)
- Transport: msgpack on ZMQ port 5557

### Navigation Decision (Rafa → Cooper)

ZMQ pub on port 5558.

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

Valid actions: `move_forward`, `move_back`, `move_left`, `move_right`, `move_up`, `move_down`, `rotate_left`, `rotate_right`, `hover`, `land`

### Health Status (Rafa → Cooper)

ZMQ pub on port 5559. Pipeline status, model load state, throughput FPS, memory usage, errors.

### Transport Summary

| Channel | Port | Publisher | Subscriber |
|---------|------|-----------|------------|
| frames | 5555 | Cooper | Rafa |
| detections | 5556 | Rafa | Cooper |
| depth | 5557 | Rafa | Cooper |
| navigation | 5558 | Rafa | Cooper |
| health | 5559 | Rafa | Cooper |

---

## Rafa's Track (AI/ML)

**Independent testing:** Use sample indoor images. No drone required. Verify JSON output against contracts above.

| # | Task | Est. Hours | Benchmark Target | Dependencies |
|---|------|------------|------------------|--------------|
| R1 | Moondream Photon detection pipeline | 3-4h | <50ms/frame | None |
| R2 | Depth Anything V2 pipeline | 1-2h | <50ms/frame | None |
| R3 | Qwen 3-VL navigation reasoning | 4-5h | <3s/keyframe | R1 output format |
| R4 | Pipeline orchestrator (all models concurrent) | 2-3h | 8+ FPS inner loop | R1, R2, R3 |
| R5 | Detection de-duplication | 1-2h | <20 unique POIs/room | R1 |
| R6 | Memory optimization (stretch) | 1-2h | <12GB total | All models |

---

## Cooper's Track (Integration)

**Independent testing:** Use mock POI JSON. No AI models required.

| # | Task | Est. Hours | Benchmark Target | Dependencies |
|---|------|------------|------------------|--------------|
| C1 | Tello SDK + frame capture | 1-2h | 30 FPS stable | None |
| C2 | State machine + flight controller | 3-4h | <100ms decision→command | C1, nav contract |
| C3 | Palantir AIP integration | 3-4h | Push every 5s | Detection contract |
| C4 | Tactical UI (live map + detection overlay) | 4-5h | 30 FPS rendering | Detection contract |
| C5 | Operator override interface | 1-2h | — | C2 |
| C6 | Demo polish + fallback | 2-3h | — | All above |

---

## Alignment Gates

Decide before building. Both tracks need agreement on these before H+0.

| # | Decision | Default |
|---|----------|---------|
| 1 | Frame format | BGR numpy, native 960x720 |
| 2 | Transport | ZMQ pub/sub (`pip install pyzmq msgpack`) |
| 3 | POI categories | 8 codes listed above |
| 4 | Navigation actions | 10 actions listed above |
| 5 | Keyframe trigger | Every 30 frames (1/sec at 30 FPS) |
| 6 | Memory budget | ~7GB models, 36GB available |
| 7 | Palantir push frequency | Batch every 5s |

---

## Benchmark Targets

| Component | Target | Acceptable | Failure |
|-----------|--------|------------|---------|
| Moondream detection/frame | 20ms | 50ms | >100ms |
| Depth Anything V2/frame | 31ms | 50ms | >100ms |
| Qwen VL decision/keyframe | 1.5s | 3s | >5s |
| Frame capture FPS | 30 | 15 | <10 |
| End-to-end frame→POI | 60ms | 120ms | >200ms |
| End-to-end frame→nav | 2s | 4s | >6s |
| Palantir push latency | 2s | 5s | >10s |
| Memory (all models) | 8GB | 12GB | >20GB |

---

## Integration Checkpoints

**H+6 is the critical gate.** If autonomous nav is not closed by then, fall back to scripted waypoints with live VLM overlay.

| Hour | Gate | What Gets Demoed |
|------|------|------------------|
| H+2 | Frame contract verified | Rafa receives frames, returns detection JSON |
| H+4 | Detection pipeline live | Moondream running on live frames, detections visible in UI |
| H+6 | Navigation loop closed | VLM decides → state machine executes → drone moves → new frame → repeat |
| H+8 | Palantir online | POIs flowing to Foundry, Workshop COP showing markers |
| H+10 | Full stress test | 5-minute autonomous flight |
| H+14 | Demo rehearsal | Full pitch + live demo dry run |
| H+16 | Fallback locked | Pre-recorded backup confirmed |

---

## Risk Mitigation

### Rafa's Risks

| Risk | Fallback |
|------|----------|
| Moondream too slow on MPS | Switch to YOLO-World |
| Qwen hallucinated nav decisions | Scripted exploration pattern |
| VLM returns malformed JSON | Schema validation + retry + fallback to hover |
| Model download at venue | **Pre-download everything tonight** |

### Cooper's Risks

| Risk | Fallback |
|------|----------|
| Tello WiFi vs venue WiFi conflict | USB WiFi adapter for dual-network |
| Tello battery (13 min) | Multiple batteries, keep demo under 5 min |
| Palantir API issues | Timebox to 3h. Cut if not working by H+8 |
| State machine safety failure | Hardware auto-land + software safety wraps |

---

## Dependency Map

```
HOUR 0: ALIGNMENT GATES (30 min, both)
   |
   +---> RAFA                              COOPER <---+
   |  R1 Moondream (H0-4)              C1 Tello Capture (H0-2)
   |  R2 Depth (H1-3)                  C2 State Machine (H1-5)
   |       |                                 |
   |       +------- H+2: Frame Contract -----+
   |       |                                 |
   |  R3 Qwen Nav (H3-8)               C4 Tactical UI (H2-7)
   |       |                                 |
   |       +------- H+4: Detection Live -----+
   |       |                                 |
   |  R4 Orchestrator (H6-9)           C3 Palantir (H5-9)
   |       |                                 |
   |       +------- H+6: Nav Loop Closed ----+
   |       |                                 |
   |  R5 De-dup (H8-10)                C5 Override (H9-11)
   |  R6 Memory (H10-12)               C6 Polish (H12-16)
   |       |                                 |
   |       +------- H+10: Stress Test -------+
   |       +------- H+14: Rehearsal ---------+
   |       +------- H+16: Fallback ----------+
```

---

## Pre-Hackathon Checklist

- [ ] Download all model weights (Moondream Photon, Depth Anything V2, Qwen 3-VL)
- [ ] Install all pip dependencies (`djitellopy`, `pyzmq`, `msgpack`, `moondream`, etc.)
- [ ] Test Tello connection and video stream
- [ ] Test Moondream on 5 sample indoor images
- [ ] Bring USB WiFi adapter (dual-network: Tello + venue)
- [ ] Bring 3+ Tello batteries
- [ ] Clone this repo on both machines
