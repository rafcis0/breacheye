# BreachEye

Autonomous VLM-driven indoor drone mapping with Palantir AIP integration. NatSec Hackathon, May 2-3, 2026.

## Team

- **Cooper** — Integration track. Drone control, state machine, Palantir AIP, frontend, deployment.
- **Rafa** — AI/ML track. Moondream Photon, Depth Anything V2, Qwen 3-VL, detection pipeline.

## Key Documents

- [CONSTITUTION.md](../CONSTITUTION.md) — Interface contracts. The law. Both tracks build to this.
- [WORKPLAN.md](../WORKPLAN.md) — Schedule, task breakdown, integration checkpoints.

## Architecture

Dual-loop: inner (local VLM, 50ms) + outer (Palantir AIP, 2-5s).

```
Tello 720p -> Moondream (20ms) -> Depth (31ms) -> State Machine -> Qwen (keyframes) -> djitellopy
                                                       |
                                         Palantir AIP (batch push every 5s)
```

## Rules

- The CONSTITUTION is the source of truth for all interface contracts. Don't deviate without updating it.
- Both tracks must be independently testable with mock data.
- Rafa tests with sample images, no drone needed.
- Cooper tests with mock JSON, no models needed.
- ZMQ pub/sub on localhost for all cross-track communication.
- Commits: `type: description` (feat, fix, refactor, docs, test, chore)
- No trailing whitespace.

## Hardware

- DJI Tello: 720p/30fps, 960x720, WiFi stream, djitellopy SDK
- Mac: 36GB Apple Silicon (MPS). No CUDA.
- Models: Moondream Photon 1.2.0, Depth Anything V2 (Core ML), Qwen 3-VL 8B (GGUF/Ollama)

## Directory Structure

```
breacheye/
├── CONSTITUTION.md      — Interface contracts (the law)
├── WORKPLAN.md          — Schedule and tasks
├── .claude/             — Claude Code config
│   ├── CLAUDE.md        — This file
│   └── settings.json    — Permissions
├── ai/                  — Rafa's track (AI/ML pipeline)
├── integration/         — Cooper's track (drone, state machine, Palantir)
├── shared/              — Shared utilities (ZMQ helpers, contract types)
└── demo/                — Demo assets, fallback data
```

## Integration Checkpoints

| Hour | Gate |
|------|------|
| H+2 | Frame contract verified |
| H+4 | Detection pipeline live |
| H+6 | Navigation loop closed (CRITICAL) |
| H+8 | Palantir online |
| H+10 | Full stress test |

## Palantir

Stretch goal. Timebox 3h. Cut if not working by H+8.
Ontology objects: TacticalPoi, FlightDecision, MissionFlight.
Workshop COP: 2D map + iframe 3D viewer + POI table + AIP chatbot.

## Research Material

Local research is in `research/` (gitignored). Start with `research/INDEX.md` for a full catalog with summaries and keywords for every file.

### Quick Reference

| Directory | Contents |
|-----------|----------|
| `research/palantir/` | 9 docs — AIP, Ontology, SDK, Agents, Workshop/Maps, CASK hardware, build walkthroughs |
| `research/hackathon-info/` | 4 docs — rules/schedule, problem statements, partner resources, venue logistics |
| `research/military/` | 4 docs — urban ops doctrine, tactical taxonomy/ATAK, competitive intel, DARPA programs |
| `research/technology/` | 8 docs — SAM2, SfM/COLMAP, edge hardware, 3D viz, indoor flight, reconstruction, Apple Silicon |
| `research/cross-domain/` | 6 docs — FPV, real estate/Matterport, SAR, construction, gaming/VR, robotics SLAM |
