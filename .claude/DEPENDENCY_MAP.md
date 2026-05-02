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

## Integration Gates

| Hour | Gate | What Must Work | Who |
|------|------|----------------|-----|
| H+2 | Frame contract | Rafa's stub pipeline receives frames, returns detections | Alpha + Rafa |
| H+4 | Detection loop | Nav interpreter consuming decisions, harness executing commands | Alpha |
| H+6 | **CRITICAL** | Full loop: frames → pipeline → nav → state machine → drone moves → new frame | Alpha + Beta |
| H+8 | Palantir go/no-go | If core works: start Theta. If not: all hands on demo polish. | PM call |
| H+10 | Stress test | 5-minute autonomous flight, count POIs, check stability | All |
| H+14 | Demo rehearsal | Full pitch + live demo dry run | All |
| H+16 | Fallback locked | Pre-recorded backup confirmed working | Beta |

## How to Use This

1. Find your session (Alpha/Beta/Theta/Aria)
2. Take the next ticket in order
3. Read the linked issue for full acceptance criteria
4. Create the branch listed in the table
5. One PR per ticket. Merge to main at integration gates.
6. If blocked, flag it — PM reassigns.
