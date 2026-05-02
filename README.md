# BreachEye

BreachEye is a local VLM-driven indoor drone mapping prototype for the NatSec hackathon. The immediate goal is a safe DJI Tello demo loop:

```text
Tello / mock frames -> Rafa VLM pipeline -> navigation decision -> safety harness -> drone command
                                      \-> detections/depth/health -> UI / Palantir path
```

The repo is set up so Cooper and Rafa can work independently against frozen ZMQ contracts. The drone never receives raw model text; all movement goes through structured schemas and the Tello safety harness.

## Current Status

- Safe Tello harness: implemented in simulator mode and hardware-adapter mode.
- Rafa pipeline: implemented as a separate ZMQ process with `stub`, `detector-only`, and `models` modes.
- H+2 contract path: mock/live frame publisher can send JPEG msgpack frames on `5555`; Rafa publishes detections, depth, navigation, and health on `5556-5559`.
- Real model adapters: placeholders exist, but model packages and weights are local-only and not committed.

## Repo Layout

- `src/breacheye/`: installable Python package, CLI, Tello safety harness, contracts, and Rafa pipeline runtime.
- `integration/`: Cooper-owned integration scripts, including the frame publisher.
- `shared/`: small cross-track command-line probes and helpers.
- `ai/`: Rafa-owned model experiments, notebooks, and local adapter work.
- `demo/`: committed mock data and fallback assets. Large videos stay local.
- `docs/`: architecture, hardware runbook, LLM boundary, and Rafa pipeline contract.
- `CONSTITUTION.md`: binding interface contract between tracks.
- `WORKPLAN.md`: hackathon schedule and checkpoints.

## Install

Use a virtual environment if possible.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[test,rafa]"
```

For Tello hardware:

```bash
pip install -e ".[hardware,test,rafa]"
```

Real model dependencies are intentionally separate for now. Do not commit model weights. Keep them under ignored local paths such as `models/` or `weights/`.

## Run The Stub Inner Loop

Terminal 1: start Rafa's pipeline.

```bash
breacheye rafa --mode stub
```

Terminal 2: publish synthetic Cooper frames.

```bash
python integration/frame_publisher.py --frames 30 --fps 5
```

Terminal 3: inspect outputs.

```bash
python shared/zmq_test_sub.py --port 5556 --channel detections --count 1
python shared/zmq_test_sub.py --port 5557 --channel depth --count 1
python shared/zmq_test_sub.py --port 5558 --channel navigation --count 1
python shared/zmq_test_sub.py --port 5559 --channel health --count 1
```

This verifies the H+2 contract without a drone or model weights.

## Frame Publisher Inputs

Synthetic frames:

```bash
python integration/frame_publisher.py --fps 5
```

Image directory:

```bash
python integration/frame_publisher.py --mock-images demo/frames --fps 2
```

Video file:

```bash
python integration/frame_publisher.py --mock-video demo/sample_flight.mp4 --fps 10
```

Live Tello:

```bash
python integration/frame_publisher.py --tello --fps 30
```

The publisher sends msgpack payloads on `5555`:

```json
{"frame_id": 42, "timestamp": 1746201234.567, "width": 960, "height": 720, "encoding": "jpeg_bgr_source", "jpeg_bytes": "..."}
```

## Safety Harness

Run simulator API:

```bash
breacheye serve --mode sim --host 127.0.0.1 --port 8000
```

Submit a structured command:

```bash
curl -X POST http://127.0.0.1:8000/commands \
  -H 'content-type: application/json' \
  -d '{"type":"takeoff","issued_by":"operator"}'
```

Run with Tello:

```bash
breacheye serve --mode tello --host 127.0.0.1 --port 8000
```

Connect the Mac to the `Tello-XXXXXX` Wi-Fi network first. Use a second network interface for internet/Palantir access.

## API

- `GET /health`: adapter, telemetry, and video status.
- `POST /commands`: submit structured commands only.
- `GET /frame/latest`: latest sampled JPEG frame.
- `GET /video.mjpeg`: MJPEG stream for frontend/human viewing.
- `WS /events`: telemetry, command results, and sampled-frame metadata.

Supported command types are `takeoff`, `land`, `emergency`, `hover`, and `rc_control`.

## Models

The inner-loop model boundary belongs in this repo; the weights do not.

- Code adapters should live under `src/breacheye/rafa/` or Rafa-owned experiments under `ai/`.
- Weights should live locally under ignored directories such as `models/` or `weights/`.
- `breacheye rafa --mode models` may attempt real adapters, publish health errors for missing dependencies, and fall back safely.
- `breacheye rafa --mode stub` must always work for demo fallback.

Preferred model stack from the workplan:

- Detection: Moondream Photon.
- Depth: Depth Anything V2.
- Navigation reasoning: Qwen 3-VL.

Check readiness:

```bash
breacheye rafa doctor
```

Require the real model stack before starting model-mode work:

```bash
breacheye rafa doctor --require-models
```

Expected local weight environment variables:

- `BREACHEYE_MOONDREAM_WEIGHTS`: local Moondream model path.
- `BREACHEYE_DEPTH_ANYTHING_WEIGHTS`: local Depth Anything V2 model path.
- `BREACHEYE_QWEN_MODEL`: local Qwen VL GGUF/model path, unless a Qwen VL model is available through Ollama.

Current fallback rule: if these are missing, `breacheye rafa --mode models` must publish degraded health and use safe stub/rule fallbacks rather than crashing the demo.

## Tests

```bash
pytest -q
```

The suite uses simulator, mocks, and in-process ZMQ. It does not require Tello hardware or model weights.

## Docs

- [Constitution](CONSTITUTION.md): frozen interface contracts.
- [Workplan](WORKPLAN.md): hackathon schedule and checkpoints.
- [Architecture](docs/architecture.md): control boundaries and process layout.
- [Hardware runbook](docs/hardware-runbook.md): Tello setup and smoke testing.
- [Rafa VLM pipeline](docs/rafa-vlm-pipeline.md): Rafa/Cooper pipeline contract.
- [Rafa model options](docs/rafa-model-options.md): current top VLM candidates and the locked first target.
- [LLM control boundary](docs/llm-control-boundary.md): safe planner interface.
