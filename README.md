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
- Flight launcher: `breacheye fly` starts the harness, Rafa, frame publisher, and nav bridge with one command.
- Real model adapters: Qwen server navigation and Depth Anything V2 depth are wired for local weights. Model files stay ignored under `models/`.
- Offline debug logs: every run writes JSONL events plus saved source frames; model depth outputs also save colorized PNGs for frame-by-frame inspection.

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

Preferred live Tello path, with the harness owning the drone connection:

```bash
python integration/frame_publisher.py --harness-url http://127.0.0.1:8000/frame/latest --fps 5
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

## One-Command Flight Loop

Use `breacheye demo` for table/demo-screen fallback mode. It can run live, recorded, or mock components and auto-degrades if Tello/video assets are unavailable:

```bash
breacheye demo --mode live --fps 5
breacheye demo --mode recorded --video demo/sample.mp4 --duration-s 20
breacheye demo --mode mock --duration-s 20
```

`demo --mode live` auto-takes off by default. Use `--no-auto-takeoff` to start the live stack without lifting off.

Run the full loop in simulator mode first:

```bash
breacheye fly --mode sim --rafa-mode stub --duration-s 20
```

When connected to Tello Wi-Fi, use the harness-owned frame source:

```bash
breacheye fly --mode tello --rafa-mode models --fps 5
```

Add `--auto-takeoff` only when the area is clear, prop guards are on, and a human is ready to land or emergency-stop:

```bash
breacheye fly --mode tello --rafa-mode models --fps 2 --auto-takeoff
```

Auto-takeoff climbs an extra 100 cm by default to reduce ground-effect drift. Override with `--takeoff-climb-cm 120`, or disable with `--takeoff-climb-cm 0`.

If hover consistently drifts backward/right, set small Tello hover trim before launch:

```bash
export BREACHEYE_TELLO_HOVER_FORWARD_BACK=6
export BREACHEYE_TELLO_HOVER_LEFT_RIGHT=-4
```

The launcher writes a preflight snapshot, starts the safety harness, starts Rafa, publishes frames into ZMQ, and bridges validated navigation decisions back to `/commands`. The Tello hardware connection stays owned by the harness; the frame publisher reads `/frame/latest`.

## Full-Flow Checklist

Ready on `main`:

- [x] Safe Tello harness: structured commands only, velocity clamp, TTL clamp, watchdog hover, keepalive.
- [x] Tello hardware adapter through `djitellopy`.
- [x] Mocked Tello adapter tests; no hardware required in CI.
- [x] Rafa ZMQ pipeline with `stub`, `detector-only`, and `models` modes.
- [x] Frame input contract on `5555`: MessagePack JPEG payloads.
- [x] Rafa outputs: detections `5556`, depth `5557`, navigation `5558`, health `5559`.
- [x] Stub mode works without model weights.
- [x] Model-mode adapters for Qwen server navigation and Depth Anything V2.
- [x] Offline logs save source frames, Rafa frames, depth `.npy`, depth PNGs, nav context, health, and event JSONL.
- [x] Spatial navigation context schema and `navigation_context_built` logs.
- [x] One-command simulator loop: `breacheye fly --mode sim --rafa-mode stub --duration-s 20`.
- [x] One-command Tello loop: `breacheye fly --mode tello --rafa-mode models --fps 5`.
- [x] Demo launcher: `breacheye demo --mode live|recorded|mock` with live-to-recorded-to-mock fallback.
- [x] Live demo auto-takeoff with `--no-auto-takeoff` escape hatch.
- [x] Harness-owned frame source, so only the harness owns the Tello connection.
- [x] Nav bridge from Rafa navigation decisions to `/commands`.
- [x] README and hardware runbook document the flow.

Partially ready:

- [ ] Real Tello flight has not been hardware-smoked in this repo session. First run should be `breacheye smoke --mode tello`.
- [ ] Model-mode readiness depends on local env vars and weights: `BREACHEYE_QWEN_MODEL`, `BREACHEYE_QWEN_MMPROJ`, `BREACHEYE_QWEN_SERVER_URL`, and `BREACHEYE_DEPTH_ANYTHING_PATH`.
- [ ] Qwen can be run through a warm `llama-server`, but model-mode should be smoke-tested again after any network/interface switch.
- [ ] VGGT-MPS is not wired yet. Current spatial context is `stub_from_current_frame`.
- [ ] Mapping/SLAM is not live. Prep/docs/context schemas exist, but real pose/frontier updates from VGGT are pending.

Still missing:

- [ ] Hardware smoke on Tello Wi-Fi: connect, telemetry, video, takeoff, hover, land.
- [ ] Run `breacheye rafa doctor --require-models` with final local model paths.
- [ ] Run `breacheye fly --mode sim --rafa-mode models --duration-s 20` with Qwen + Depth Anything before touching the drone.
- [ ] Run the Tello loop without auto takeoff first: `breacheye fly --mode tello --rafa-mode models --fps 5`; verify `/health`, logs, frame publisher logs, and Rafa nav logs.
- [ ] Only after that, run `breacheye fly --mode tello --rafa-mode models --fps 2 --auto-takeoff`.
- [ ] Add VGGT-MPS runner once the download completes.
- [ ] Convert VGGT output into real `SpatialNavigationContext`: pose, looking direction, visited regions, frontiers, known objects.
- [ ] Feed real spatial context into the Qwen prompt. It is logged now, but not yet injected into the navigator prompt.
- [ ] Add UI/report view for reconstruction, camera frustum, and model decision trail.

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

- Navigation reasoning: Qwen3-VL-2B GGUF through `llama-server` for the current demo path.
- Depth: Depth Anything V2 Small through Transformers/MPS.
- Fast VLM candidate: Apple FastVLM-0.5B is downloaded and runnable locally, but it is not promoted to navigator until strict JSON output is solved.
- Detection fallback/research: Moondream is available locally but currently too slow through the tested GGUF path.

Check readiness:

```bash
breacheye rafa doctor
```

Require the real model stack before starting model-mode work:

```bash
breacheye rafa doctor --require-models
```

Expected local weight environment variables:

- `BREACHEYE_QWEN_MODEL`: local Qwen VL GGUF path.
- `BREACHEYE_QWEN_MMPROJ`: local Qwen multimodal projector path.
- `BREACHEYE_QWEN_SERVER_URL`: warm `llama-server` URL, preferred for model-mode demos.
- `BREACHEYE_QWEN_MAX_TOKENS`: optional response cap; default is `32` for faster action decisions.
- `BREACHEYE_DEPTH_ANYTHING_PATH`: local Depth Anything V2 model directory.
- `BREACHEYE_DEPTH_ANYTHING_DEVICE`: optional device override, usually `mps` on Apple Silicon.
- `BREACHEYE_MOONDREAM_WEIGHTS`: optional local Moondream path for research fallback work.

Depth artifacts are written under `logs/<run_id>/rafa/depth/frame-XXXXXXXX.png`, with matching JSONL `depth_image_saved` events. Source input frames are written under `logs/<run_id>/rafa/frames/`.

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
- [Rafa benchmark results](docs/rafa-benchmark-results.md): download/benchmark status and commands.
- [Offline debug logging](docs/offline-debug-logging.md): JSONL logs for Tello Wi-Fi runs.
- [3D reconstruction plan](docs/three-d-reconstruction-plan.md): staged mapping approach.
- [Spatial VLM context](docs/spatial-vlm-context.md): map memory and camera-view context for navigation.
- [LLM control boundary](docs/llm-control-boundary.md): safe planner interface.
