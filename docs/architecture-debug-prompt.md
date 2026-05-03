You are debugging the BreachEye autonomous drone mapping system — a dual-loop VLM-driven indoor drone platform built for a NatSec hackathon (May 2-3, 2026). Two developers: Cooper (integration track — drone control, state machine, Palantir, frontend) and Rafa (AI/ML track — Moondream, Depth Anything, Qwen VLM, detection pipeline). This document contains the full system architecture. You should not need to read any files to understand how the system works.

## System Architecture Overview

BreachEye flies a DJI Tello drone (720p/30fps, 960x720, WiFi, djitellopy SDK) through an indoor environment. An inner VLM loop (~50ms) runs Moondream for object detection and Depth Anything V2 for depth estimation. An outer loop (~2-5s) runs Qwen 3-VL for navigation decisions. A state machine governs flight lifecycle. An optional Palantir AIP layer provides C2 visualization.

Hardware: Mac 36GB Apple Silicon (MPS, no CUDA). Tello creates its own WiFi network — internet access requires a second interface.

## Process Tree & Transport Map

```
┌─────────────────────────────────────────────────────────────────────┐
│                        breacheye demo / fly                         │
│                    (flight.py — process orchestrator)                │
└─────────┬──────────┬──────────────┬────────────┬───────────────┬────┘
          │          │              │            │               │
    ┌─────▼──────┐ ┌─▼────────┐ ┌──▼──────────┐ ┌▼────────────┐ ┌▼──────────┐
    │  harness   │ │  rafa    │ │frame_publisher│ │nav_interpreter│ │map_builder│
    │ (FastAPI)  │ │(pipeline)│ │  (ZMQ PUB)   │ │ (ZMQ→HTTP)  │ │(depth→3D) │
    │ port 8000  │ │          │ │  port 5555   │ │             │ │           │
    └─────┬──────┘ └──┬───┬──┘ └──────────────┘ └──────┬──────┘ └───────────┘
          │           │   │                             │
   HTTP/WS│      ZMQ  │   │ ZMQ                    HTTP │
          │    ┌──────┘   └────────┐                    │
          │    │ 5556,5557,5558,5559│                    │
          │    ▼                    ▼                    │
          │  detections         nav decisions            │
          │  depth              health                   │
          │                                              │
          ◄──────────────────────────────────────────────┘
                    POST /commands
```

## ZMQ Channels (all TCP localhost, pub/sub)

| Port | Channel    | Publisher          | Subscriber(s)                    | Wire Format |
|------|------------|--------------------|----------------------------------|-------------|
| 5555 | frames     | frame_publisher    | RafaPipeline (ZmqFrameReceiver)  | **msgpack** |
| 5556 | detections | RafaPipeline       | HarnessRuntime ZMQ bridge, PalantirWriter | JSON |
| 5557 | depth      | RafaPipeline       | (none currently)                 | **msgpack** |
| 5558 | navigation | RafaPipeline       | NavInterpreter (CONFLATE=1)      | JSON        |
| 5559 | health     | RafaPipeline       | (none currently)                 | JSON        |

**CRITICAL: Frames (5555) and depth (5557) use msgpack. Everything else uses JSON. Mixing these up is a common bug.**

## HTTP Endpoints (harness, port 8000)

| Method | Path                    | Request Body          | Response                                    |
|--------|-------------------------|-----------------------|---------------------------------------------|
| GET    | /health                 | —                     | {mode, telemetry: DroneTelemetry, video: {}} |
| POST   | /commands               | DroneCommand JSON     | CommandResult JSON                          |
| POST   | /operator-command       | OperatorCommand JSON  | {action, state, success}                    |
| POST   | /video/start            | —                     | {running}                                   |
| POST   | /video/stop             | —                     | {stopped, running}                          |
| GET    | /frame/latest           | —                     | JPEG bytes (image/jpeg)                     |
| GET    | /map/point-cloud/latest | —                     | JSON point cloud                            |
| GET    | /video.mjpeg            | —                     | MJPEG multipart stream                      |
| WS     | /events                 | —                     | JSON {topic, message} per bus event         |

## Event Bus Topics (AsyncEventBus, in-process pub/sub)

| Topic                   | Publisher              | Subscriber(s)          |
|-------------------------|------------------------|------------------------|
| drone.telemetry         | SafetyController       | WS /events             |
| drone.command_results   | SafetyController       | WS /events             |
| drone.frames.llm        | TelloVideoPump         | WS /events             |
| drone.detections        | HarnessRuntime ZMQ bridge | WS /events          |
| drone.state_change      | FlightStateMachine     | WS /events             |
| drone.paused            | FlightStateMachine     | WS /events             |
| drone.resumed           | FlightStateMachine     | WS /events             |
| drone.abort             | FlightStateMachine     | WS /events             |
| drone.nav_decision      | (nav bridge)           | ExplorationTracker     |
| drone.battery_warning   | BatteryMonitor         | (logged)               |
| drone.exploration_event | ExplorationTracker     | (logged)               |

## Full Data Flow

### 1. Frame Capture → VLM Detection → Navigation → Command Execution

```
Tello SDK ──► frame_publisher ──msgpack──► ZMQ 5555
                                              │
                                    ZmqFrameReceiver
                                              │
                                     RafaPipeline._tick()
                                    ┌─────────┼─────────┐
                                    ▼         ▼         ▼
                              detect()    estimate()  decide()
                            (Moondream)  (DepthAnything) (Qwen)
                                    │         │         │
                                    ▼         ▼         ▼
                              DetectionOut DepthOut  NavigationOut
                              JSON→5556  msgpack→5557 JSON→5558
                                                        │
                                              NavInterpreter (SUB)
                                                        │
                                              POST /commands
                                                        │
                                              SafetyController.execute()
                                                        │
                                              DroneAdapter.rc_control()
                                                        │
                                              Tello SDK command
```

### 2. State Machine Lifecycle

```
PREFLIGHT ──► TAKEOFF ──► EXPLORING ◄──► INVESTIGATING
    │             │            │              │
    │             │            ▼              ▼
    │             │        RETURNING ─────► LANDING ──► COMPLETE
    │             │                            ▲
    └─────────────┴────────────────────────────┘
         (LANDING reachable from ALL non-terminal states)
```

Guards:
- TAKEOFF: preflight_check() must pass (connected=true, battery > 20%)
- LANDING: drone must be flying (skipped from PREFLIGHT)

Entry actions:
- TAKEOFF → adapter.takeoff()
- LANDING → adapter.land()
- EXPLORING/INVESTIGATING/RETURNING → adapter.hover()

### 3. Battery Monitoring

BatteryMonitor polls adapter every 2s:
- battery <= 15% → force RETURNING (if in EXPLORING/INVESTIGATING/TAKEOFF/RETURNING)
- battery <= 10% → force LANDING (escalation from RETURNING)
- Publishes drone.battery_warning events

### 4. Operator Controls

OperatorCommand via POST /operator-command:
- ABORT → clears paused flag, transitions to LANDING from any non-terminal (skips PREFLIGHT/COMPLETE)
- PAUSE → sets _paused=true, hovers drone, publishes drone.paused. accepts_nav() returns false.
- RESUME → clears _paused, publishes drone.resumed. accepts_nav() resumes.

### 5. Navigation Gating

NavInterpreter reads ZMQ 5558, translates NavigationAction to DroneCommand, POSTs to /commands:
- move_forward/back/left/right → rc_control with directional velocity + duration
- rotate_left/right → rc_control with yaw
- hover → hover command
- land → land command
- Confidence < 0.5 → forced hover
- 3+ consecutive malformed → hover + log

State machine gates this: accepts_nav() returns true ONLY in EXPLORING or INVESTIGATING and not paused.

## Schema Reference

### Wire Schemas (Pydantic, extra="forbid")

**FrameInput** (msgpack on 5555):
```
frame_id: int (>=0), timestamp: float, jpeg_bytes: bytes (min_length=1),
width: int|None (>0), height: int|None (>0), encoding: str = "jpeg_bgr_source"
```

**DetectionOutput** (JSON on 5556):
```
frame_id: int (>=0), timestamp: float, detections: list[Detection], processing_ms: int (>=0)
```

**Detection**:
```
id: str, category: PoiCategory, label: str, description: str = "",
confidence: float (0.0-1.0), bbox_2d: BBox2D, threat_level: ThreatLevel,
detection_model: str
```

**BBox2D**: `x1, y1, x2, y2: int (>=0)` — validated: x2 > x1, y2 > y1

**DepthOutput** (msgpack on 5557):
```
frame_id: int, timestamp: float, shape: tuple[int,int], dtype: "float32",
unit: "relative_0_near_1_far", depth_bytes: bytes (length must == shape[0]*shape[1]*4)
```

**NavigationOutput** (JSON on 5558):
```
frame_id: int, timestamp: float, decision: NavigationDecision
```

**NavigationDecision**:
```
action: NavigationAction, params: dict = {}, confidence: float (0.0-1.0),
reasoning: str = "", exploration_state: ExplorationState = "exploring"
```

**HealthOutput** (JSON on 5559):
```
pipeline_status: "starting"|"ready"|"degraded"|"error",
models_loaded: dict[str, ModelStatus], throughput: Throughput,
memory: MemoryStatus, errors: list[str], timestamp: float
```

**DroneCommand** (HTTP POST /commands):
```
command_id: str (uuid), type: CommandType, issued_by: str = "unknown",
ttl_ms: int|None (50-5000), payload: RCControlPayload|None
```
Validation: rc_control requires payload; others must not have payload.

**RCControlPayload**: `left_right, forward_back, up_down, yaw: int (-100..100), duration_ms: int (50..2000)`

**OperatorCommand** (HTTP POST /operator-command):
```
action: "abort"|"pause"|"resume", issued_by: str = "operator"
```

### Enums

**PoiCategory**: T1-01 (Entry/Exit), T1-02 (Fatal Funnel), T1-03 (Stairs/Vertical), T2-02 (Threat Indicator), T2-03 (Chokepoint), T3-01 (Utility Panel), T4-01 (Structural Damage), ROOM (Room/Open Area)

**ThreatLevel**: HOT, WARM, CAUTION, CLEAR, INFO

**NavigationAction**: move_forward, move_back, move_left, move_right, move_up, move_down, rotate_left, rotate_right, hover, land

**ExplorationState**: exploring, investigating_poi, returning, obstacle_avoidance, coverage_complete, low_battery

**FlightState**: preflight, takeoff, exploring, investigating, returning, landing, complete

**CommandType**: takeoff, land, emergency, hover, rc_control

## Process Configurations (Demo Modes)

| Component         | --live              | --recorded             | --mock                |
|-------------------|---------------------|------------------------|-----------------------|
| Harness mode      | tello               | sim                    | sim                   |
| Frames (5555)     | frame_publisher --tello | playback.py --video  | frame_publisher (synthetic) |
| Detections (5556) | RafaPipeline        | playback.py            | mock_detections.py    |
| Nav (5558)        | RafaPipeline        | mock_navigation.py     | mock_navigation.py    |
| Health (5559)     | RafaPipeline        | mock_telemetry.py      | mock_telemetry.py     |
| Nav interpreter   | YES                 | YES                    | YES                   |

Auto-fallback chain: live → recorded (if Tello fails 5s probe) → mock (if video file missing).

## Debug Entry Points

### Frame pipeline not flowing
1. Check frame_publisher process is running
2. `python shared/zmq_test_sub.py --port 5555 --channel frames` — are frames arriving?
3. Check Tello WiFi connection (live mode)
4. frame_publisher logs in `{log_dir}/{run_id}/frame_publisher/events.jsonl`
5. Common: Tello WiFi drops, publisher keeps running but yields no frames

### Detections not appearing
1. Check RafaPipeline process / mock_detections.py is running
2. `python shared/zmq_test_sub.py --port 5556 --channel detections` — sniff ZMQ
3. Check rafa logs `{log_dir}/{run_id}/rafa/events.jsonl`
4. HarnessRuntime has ZMQ bridge (SUB on 5556) that republishes to bus → WS
5. Common: model weights missing, ModelUnavailable caught silently, falls back to stub

### Navigation not working
1. Check NavInterpreter process is running
2. Sniff ZMQ 5558 for NavigationOutput messages
3. NavInterpreter logs decisions to `{log_dir}/{run_id}/nav_interpreter/events.jsonl`
4. Check state machine: accepts_nav() must be true (state=EXPLORING|INVESTIGATING, not paused)
5. Check confidence >= 0.5 (below this, NavInterpreter forces hover)
6. Check safety controller: velocity clamped to ±35, duration clamped to TTL
7. Common: Qwen output not parseable as JSON, falls back to SafeRuleNavigator (hover/rotate only)

### State machine stuck
1. Query /health for current state via telemetry
2. Subscribe to WS /events, filter topic=drone.state_change
3. Check battery: BatteryMonitor forces RETURNING at ≤15%, LANDING at ≤10%
4. Check pause state: POST /operator-command with action=resume
5. Common: preflight_check fails (battery ≤ 20%), blocking TAKEOFF transition

### Palantir not receiving data
1. Check FOUNDRY_HOST and FOUNDRY_TOKEN env vars
2. PalantirWriter subscribes to ZMQ 5556 — detections must flow first
3. Batch push every 5s, deduplicates by grid cell (80px buckets)
4. Rate limit: 5000 req/min per user
5. Common: action type not created in Ontology Manager, returns 404

## Key Invariants

1. **Wire format**: Ports 5555 and 5557 are msgpack. Ports 5556, 5558, 5559 are JSON. Mixing kills the pipeline silently.
2. **Frame dimensions**: 960x720, BGR source, JPEG-compressed for transport. Do NOT resize before publishing.
3. **Confidence threshold**: NavInterpreter treats confidence < 0.5 as hover.
4. **Battery thresholds**: preflight requires > 20%, RTL at ≤ 15%, emergency land at ≤ 10%.
5. **Safety bounds**: RC velocity clamped to ±35, duration to TTL (default 750ms, max 1000ms). Watchdog hovers on stale commands (> 2s).
6. **Keepalive**: SafetyController sends neutral RC every 5s when flying to prevent Tello auto-land timeout.
7. **ZMQ CONFLATE=1**: NavInterpreter uses CONFLATE — always reads latest message, discards queue. This is intentional for ~1Hz nav decisions.
8. **StrictModel (extra="forbid")**: All Pydantic schemas reject unknown fields. Extra fields in JSON → ValidationError.
9. **Depth values**: Relative 0.0 (near) to 1.0 (far). Obstacle threshold ~0.15 for "close". NOT metric distances.
10. **Keyframe trigger**: Every 30 frames triggers the outer Qwen loop.
11. **Model fallback chain**: Moondream → (ModelUnavailable) → StubDetector. Qwen → SmolVLM → SafeRuleNavigator. DepthAnything → (unavailable) → StubDepthEstimator.

## File Map

```
src/breacheye/
├── adapters/
│   ├── base.py          DroneAdapter ABC, DroneState
│   ├── sim.py           SimAdapter (testing)
│   └── tello.py         TelloAdapter (hardware)
├── rafa/
│   ├── __init__.py      Exports RafaPipeline, RafaPipelineConfig
│   ├── schemas.py       All wire format Pydantic models
│   ├── codec.py         msgpack/JSON encode/decode
│   ├── jpeg.py          JPEG→BGR decode
│   ├── receiver.py      ZmqFrameReceiver
│   ├── adapters.py      Detection/Depth/Nav adapter ABCs + stubs
│   ├── models.py        Real model adapters (Moondream, DepthAnything, Qwen, SmolVLM)
│   ├── orchestrator.py  RafaPipeline main loop
│   ├── readiness.py     Doctor/readiness checks
│   └── spatial_context.py  SpatialNavigationContext builder
├── battery_monitor.py   Async battery poller → FSM transitions
├── bus.py               AsyncEventBus (in-process pub/sub)
├── cli.py               Argparse CLI (serve/smoke/fly/demo/rafa/nav/...)
├── exploration_tracker.py  ExplorationState → FlightState mapper
├── flight.py            Multi-process orchestrator + demo launcher
├── models.py            DroneCommand, DroneTelemetry, CommandResult
├── monitor.py           Live run watcher (polls health, tails logs)
├── nav_interpreter.py   ZMQ 5558 → POST /commands bridge
├── offline.py           Preflight metadata, offline bundles
├── operator.py          OperatorCommand model + handler
├── planner.py           Scripted room scan sequence
├── runlog.py            JSONL logger with artifact storage
├── safety.py            SafetyController (velocity bounds, TTL, watchdog)
├── service.py           FastAPI harness (HarnessRuntime, endpoints)
├── state_machine.py     FlightStateMachine (7 states, guards, bus events)
└── video.py             FrameStore, TelloVideoPump, encode_jpeg

integration/
├── frame_publisher.py   ZMQ PUB on 5555 (various frame sources)
├── palantir_writer.py   Batch push detections → Foundry Ontology
└── map_builder.py       Depth logs → 3D point cloud

demo/
├── playback.py          Video + synced detections (recorded mode)
├── mock_detections.py   Synthetic DetectionOutput → ZMQ 5556
├── mock_navigation.py   Synthetic NavigationOutput → ZMQ 5558
├── mock_telemetry.py    Synthetic HealthOutput → ZMQ 5559
├── mock_detections.json Pre-scripted detection sequence (22 frames)
├── sample_pois.csv      16 TacticalPoi rows for Palantir
└── sample_decisions.csv 15 FlightDecision rows for Palantir
```
