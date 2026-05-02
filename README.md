# BreachEye Tello Harness

Python harness for controlling a Ryze/DJI Tello through a strict safety boundary while exposing telemetry, full video, and sampled frames for an eventual LLM controller.

This repo is intentionally structured so an LLM, frontend, or teammate process can sit outside the harness and communicate through structured commands and observations. The drone never receives raw model text.

## Docs

- [Architecture](docs/architecture.md): control boundaries, SDK facts, and video/LLM split.
- [Hardware runbook](docs/hardware-runbook.md): setup, smoke tests, API flight commands, and troubleshooting.
- [LLM control boundary](docs/llm-control-boundary.md): how a planner should consume frames/telemetry and emit safe commands.
- [Research index](docs/research-index.md): source notes from SDK docs, DJITelloPy docs/repo, and community/video-stream references.

## Repo Layout

- `src/breacheye/`: installable Python package, CLI, Tello harness, and Rafa stub pipeline.
- `ai/`: Rafa-owned AI/ML track artifacts and future model assets or scripts.
- `integration/`: Cooper-owned drone, state-machine, Palantir, and frontend integration work.
- `shared/`: cross-track helpers and contract utilities when they need to be consumed outside the package.
- `demo/`: mock data, fallback assets, and rehearsal material.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
```

Hardware/video support:

```bash
pip install -e ".[hardware,test]"
```

## Run In Simulator Mode

```bash
breacheye serve --mode sim --host 127.0.0.1 --port 8000
```

Submit a command:

```bash
curl -X POST http://127.0.0.1:8000/commands \
  -H 'content-type: application/json' \
  -d '{"type":"takeoff","issued_by":"operator"}'
```

## Run With Tello

1. Connect the computer to the `Tello-XXXXXX` Wi-Fi network.
2. Install hardware extras.
3. Start the service:

```bash
breacheye serve --mode tello --host 127.0.0.1 --port 8000
```

The service sends SDK commands through `djitellopy`, starts video with `streamon`, samples low-rate frames for the LLM path, and exposes MJPEG video for a future frontend.

## API

- `GET /health`: adapter, flying, telemetry, video status.
- `POST /commands`: submit structured commands only.
- `GET /frame/latest`: latest sampled JPEG frame for an LLM/controller.
- `GET /video.mjpeg`: MJPEG stream for frontend/human viewing.
- `WS /events`: telemetry, command results, and sampled-frame metadata.

Supported command types are `takeoff`, `land`, `emergency`, `hover`, and `rc_control`.
