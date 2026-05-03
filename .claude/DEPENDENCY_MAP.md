# BreachEye Dependency Map

Work items, dependencies, session assignments, and execution order.
Each ticket is one PR. Check the linked issue before starting work.

## Dependency Graph

```
ARIA (immediate, unblocks others)          ALPHA (drone loop)
┌─────────────────────────┐                ┌──────────────────────────────────┐
│ #8  Mock Data Gen ──────────────────────>│ #16 Nav Interpreter: basic ──┐   │
│ #9  Contract Validation  │               │                              │   │
│ #14 Palantir Ontology Prep│              │ #17 Nav: confidence/error ◄──┘   │
└─────────────────────────┘                │         │                        │
        │                                  │ #15 State Machine: core ◄────────┘
        │                                  │         │
        │                                  │    ┌────┴─────┬──────────┐       │
        │                                  │ #18 Battery  #20 Explore #19 Ops │
        │                                  └──────────────────────────────────┘
        │
        │         BETA (frontend)                     THETA (stretch)
        │         ┌──────────────────────────┐        ┌────────────────────┐
        │         │ #21 UI scaffold + MJPEG  │        │ #24 Palantir batch │
        │         │      │                   │        │      │             │
        │         │ ┌────┼──────┐            │        │ #26 Workshop COP   │
        │         │ │    │      │            │        │      │             │
        └────────>│ #22 HUD  #23 Bbox  #25 Map│       │ #27 AIP Chatbot   │
                  │         │                │        └────────────────────┘
                  │ #28 Recorded playback ◄──┘
                  │      │                   │
                  │ #29 CLI launcher         │
                  └──────────────────────────┘
```

## Critical Path

```
#16 (nav basic) → #15 (state machine) → integration test with Rafa → #13 (demo fallback)
```

This is the path to a working demo. Everything else is parallel or stretch.

## Session Assignments

### Alpha — Drone Loop
Sequential. Each PR builds on the last.

| Order | Issue | Title | Size | Depends On | Branch |
|:-----:|-------|-------|:----:|------------|--------|
| 1 | [#16](https://github.com/rafcis0/breacheye/issues/16) | Nav Interpreter: basic action mapping | S | — | `cooper/nav-interpreter-basic` |
| 2 | [#17](https://github.com/rafcis0/breacheye/issues/17) | Nav Interpreter: confidence + error handling | S | #16 | `cooper/nav-error-handling` |
| 3 | [#15](https://github.com/rafcis0/breacheye/issues/15) | State Machine: core states + transitions | M | #16 | `cooper/state-machine-core` |
| 4 | [#18](https://github.com/rafcis0/breacheye/issues/18) | State Machine: battery + telemetry monitoring | S | #15 | `cooper/battery-monitor` |
| 5 | [#20](https://github.com/rafcis0/breacheye/issues/20) | State Machine: exploration state tracking | S | #15 | `cooper/exploration-tracking` |
| 6 | [#19](https://github.com/rafcis0/breacheye/issues/19) | State Machine: operator command injection | S | #15 | `cooper/operator-commands` |

### Beta — Frontend
#21 first, then #22/#23/#25 can parallel. Demo fallback last.

| Order | Issue | Title | Size | Depends On | Branch |
|:-----:|-------|-------|:----:|------------|--------|
| 1 | [#21](https://github.com/rafcis0/breacheye/issues/21) | Tactical UI: scaffold + MJPEG feed | M | — | `cooper/ui-scaffold` |
| 2 | [#22](https://github.com/rafcis0/breacheye/issues/22) | Tactical UI: telemetry HUD | S | #21 | `cooper/ui-telemetry` |
| 3 | [#23](https://github.com/rafcis0/breacheye/issues/23) | Tactical UI: detection bbox overlay | M | #21 | `cooper/ui-detection-overlay` |
| 4 | [#25](https://github.com/rafcis0/breacheye/issues/25) | Tactical UI: 2D tactical map | M | #21 | `cooper/ui-tactical-map` |
| 5 | [#28](https://github.com/rafcis0/breacheye/issues/28) | Demo Fallback: recorded playback | S | #8 (Aria) | `cooper/demo-playback` |
| 6 | [#29](https://github.com/rafcis0/breacheye/issues/29) | Demo Fallback: CLI launcher | S | #28 | `cooper/demo-launcher` |

### Theta — Stretch (Palantir)
Only start if Alpha + Beta are solid by H+8.

| Order | Issue | Title | Size | Depends On | Branch |
|:-----:|-------|-------|:----:|------------|--------|
| 1 | [#24](https://github.com/rafcis0/breacheye/issues/24) | Palantir: batch POI writer | M | Ontology on-site | `cooper/palantir-writer` |
| 2 | [#26](https://github.com/rafcis0/breacheye/issues/26) | Palantir: Workshop COP dashboard | M | #24 | `cooper/palantir-workshop` |
| 3 | [#27](https://github.com/rafcis0/breacheye/issues/27) | Palantir: AIP tactical chatbot | S | #26 | `cooper/palantir-chatbot` |

### Aria — Shared Infra
All independent. Start immediately.

| Order | Issue | Title | Size | Depends On | Branch |
|:-----:|-------|-------|:----:|------------|--------|
| 1 | [#8](https://github.com/rafcis0/breacheye/issues/8) | Mock Data Generators | S | — | `aria/mock-data` |
| 2 | [#9](https://github.com/rafcis0/breacheye/issues/9) | Contract Validation Tests | S | — | `aria/contract-tests` |
| 3 | [#14](https://github.com/rafcis0/breacheye/issues/14) | Palantir Ontology Prep | S | — | `aria/palantir-prep` |

## Completed Tracks

### Core System (DONE — PRs #1-#55)

All original Alpha, Beta, Aria, and Theta tickets complete:
- Flight harness, state machine, battery monitor, operator controls
- Nav interpreter with confidence thresholding + error escalation
- UI scaffold, telemetry HUD, detection overlay, tactical map, demo modes
- Palantir batch writer, mock data generators, contract tests

### Frontend Redesign (DONE — PRs #68-#71)

All 12 redesign tickets (#56-#67) complete:
- Tailwind v4 + shadcn/ui + OKLCH design tokens
- Three-zone layout (video + right panel + bottom bar)
- Glassmorphism panels, compact header telemetry, status bar
- Flight controls safety (hold-to-activate EMERGENCY)
- Mission-phase state management (pre-flight / active / post-flight)
- Map3D orbit controls + post-flight promotion

---

## Active Feature Tracks

### Smoke Test — Cooper (Manual)

| Issue | Title | Tier | Status |
|-------|-------|------|--------|
| [#87](https://github.com/rafcis0/breacheye/issues/87) | Full-stack smoke test: models + pipeline + flight | Moderate | TODO |

No code changes. Download weights, install model deps, configure env, validate real VLM inference.

### Depth-Driven Obstacle Avoidance — Aria

Sequential. Depth pipeline must be functional.

```
#72 Depth proximity alert ──► #73 Nav forward guard ──► #74 Threshold tuning
```

| Order | Issue | Title | Tier | Depends On |
|:-----:|-------|-------|------|------------|
| 1 | [#72](https://github.com/rafcis0/breacheye/issues/72) | Depth proximity alert publisher in rafa pipeline | Simple | Depth pipeline |
| 2 | [#73](https://github.com/rafcis0/breacheye/issues/73) | NavInterpreter depth-aware forward guard | Moderate | #72 |
| 3 | [#74](https://github.com/rafcis0/breacheye/issues/74) | Depth threshold tuning for indoor environments | Complex | #73 |

### Autonomous Doorway Transit — Aria

Sequential. Detection pipeline must be functional.

```
#75 Doorway detection ──► #76 Transit sequence ──► #77 Multi-room tracking
```

| Order | Issue | Title | Tier | Depends On |
|:-----:|-------|-------|------|------------|
| 1 | [#75](https://github.com/rafcis0/breacheye/issues/75) | Doorway detection and centering logic | Simple | Detection pipeline |
| 2 | [#76](https://github.com/rafcis0/breacheye/issues/76) | Doorway transit sequence in navigation logic | Complex | #75 |
| 3 | [#77](https://github.com/rafcis0/breacheye/issues/77) | Multi-room state tracking in ExplorationTracker | Simple | #76 |

### Post-Flight Building Report — Rafa

#80 (schema) first, then #78 + #79 sequential.

```
#80 Schema definition ──► #78 Data accumulator ──► #79 Report generator
```

| Order | Issue | Title | Tier | Depends On |
|:-----:|-------|-------|------|------------|
| 1 | [#80](https://github.com/rafcis0/breacheye/issues/80) | Building report schema definition | Trivial | — |
| 2 | [#78](https://github.com/rafcis0/breacheye/issues/78) | Flight data accumulator for post-flight report | Simple | #80 |
| 3 | [#79](https://github.com/rafcis0/breacheye/issues/79) | Post-flight building report generator | Moderate | #78 |

### VPS Floor Scanner — CLOSED

~~#81, #82, #83~~ — Closed. Tello has no downward camera. Floor plan will be synthesized post-flight from accumulated POIs, depth-inferred walls, and dead-reckoned drone path. Folded into building report track (#78-#80).

### Depth-Based Room Volume Estimation — CLOSED

~~#84, #85, #86~~ — Closed. Depth Anything V2 produces relative depth, not metric — can't derive room dimensions. Dead-reckoned pose drift makes multi-angle accumulation unreliable. Room characterization served by VLM descriptions (already in pipeline) and post-flight COLMAP (already scoped).

### Palantir Stretch (unchanged)

| Order | Issue | Title | Tier | Depends On |
|:-----:|-------|-------|------|------------|
| 1 | [#12](https://github.com/rafcis0/breacheye/issues/12) | Palantir AIP: Ontology + Workshop + Chatbot | L | On-site staff |
| 2 | [#25](https://github.com/rafcis0/breacheye/issues/25) | Workshop COP dashboard | M | #12 |
| 3 | [#27](https://github.com/rafcis0/breacheye/issues/27) | AIP tactical chatbot | S | #25 |

### Rafa's Open ML Tickets

| Issue | Title | Status |
|-------|-------|--------|
| [#41](https://github.com/rafcis0/breacheye/issues/41) | Benchmark and reduce Qwen navigation latency | In progress |
| [#42](https://github.com/rafcis0/breacheye/issues/42) | Harden offline Tello run mode and log bundle | Done |
| [#43](https://github.com/rafcis0/breacheye/issues/43) | Real Tello hardware smoke test (model mode) | Blocked on #87 |
| [#44](https://github.com/rafcis0/breacheye/issues/44) | Moondream MPS/Metal blocker | Blocked (dead path) |
| [#45](https://github.com/rafcis0/breacheye/issues/45) | First-pass 3D map artifact | Partial |
| [#46](https://github.com/rafcis0/breacheye/issues/46) | FastVLM benchmark | Not started |
| [#47](https://github.com/rafcis0/breacheye/issues/47) | Demo script/checklist | Not started |
| [#48](https://github.com/rafcis0/breacheye/issues/48) | FlyMeThrough 3D reconstruction | Not started |
| [#49](https://github.com/rafcis0/breacheye/issues/49) | Spatial map memory for nav VLM | Partial |

---

## Full Dependency Overview

```
                         COMPLETED
    ┌─────────────────────────────────────────────┐
    │ Core system (Alpha/Beta/Aria/Theta) ✓       │
    │ Frontend redesign (#56-#67) ✓               │
    └─────────────────────────────────────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
    ┌──────────────┐ ┌──────────┐ ┌──────────────┐
    │ #87 Smoke    │ │ ARIA     │ │ RAFA         │
    │ Test (Cooper)│ │          │ │              │
    └──────────────┘ │ #72→#73  │ │ #80→#78→#79 │
                     │   →#74   │ │ (report)     │
                     │ (depth   │ │              │
                     │  avoid)  │ │ #81→#82→#83 │
                     │          │ │ (floor scan) │
                     │ #75→#76  │ │              │
                     │   →#77   │ │ #84→#85→#86 │
                     │ (doorway │ │ (room volume)│
                     │  transit)│ │              │
                     └──────────┘ └──────────────┘
```

## How to Use This

1. Find your session (Alpha/Beta/Theta/Aria)
2. Take the next ticket in order
3. Read the linked issue for full acceptance criteria
4. Create the branch listed in the table
5. One PR per ticket. Merge to main at integration gates.
6. If blocked, flag it — PM reassigns.
