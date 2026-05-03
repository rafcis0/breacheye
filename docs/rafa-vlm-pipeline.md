# Rafa VLM Pipeline Contract

This document records Rafa's process boundary for Cooper's integration work. `CONSTITUTION.md` remains the binding cross-track source of truth; this file explains the implementation contract in repo-local terms.

## Process Boundary

Run Rafa's VLM pipeline as a separate local process:

```bash
breacheye rafa --mode stub
```

The process subscribes to Cooper's frame publisher and publishes validated perception, depth, navigation, and health payloads over localhost ZMQ pub/sub.

## Channels

| Channel | Port | Direction | Format |
|---------|------|-----------|--------|
| frames | 5555 | Cooper -> Rafa | msgpack `{frame_id, timestamp, jpeg_bytes}` |
| detections | 5556 | Rafa -> Cooper | JSON detection payload |
| depth | 5557 | Rafa -> Cooper | msgpack depth payload |
| navigation | 5558 | Rafa -> Cooper | JSON navigation payload |
| health | 5559 | Rafa -> Cooper | JSON health payload |

Payloads may include the optional frame metadata fields from `CONSTITUTION.md`, such as `width`, `height`, and `encoding`.

## Frame Wire Format

`jpeg_bytes` is the frozen wire format. Cooper sends JPEG-compressed bytes in msgpack bin format. Rafa decodes those bytes to BGR numpy arrays internally with OpenCV:

```python
cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8), cv2.IMREAD_COLOR)
```

BGR numpy arrays are internal only. They are not the ZMQ wire format.

For offline debugging, Rafa saves each received JPEG under `logs/<run_id>/rafa/frames/frame-XXXXXXXX.jpg` and records that path in the `frame_received` JSONL event. The frame publisher also saves the sent JPEG under `logs/<run_id>/frame_publisher/frames/` so we can compare both sides of the ZMQ boundary after a Tello Wi-Fi run.

Rafa also saves a colorized PNG for each depth output under `logs/<run_id>/rafa/depth/frame-XXXXXXXX.png` and records that path in a `depth_image_saved` JSONL event.

## Outputs

Rafa validates every outgoing payload against Pydantic schemas before publishing.

- Detections on `5556`: POI JSON structure from `CONSTITUTION.md`.
- Depth on `5557`: msgpack `{frame_id, timestamp, shape, dtype, unit, depth_bytes}` where `depth_bytes` is raw `float32`.
- Model-mode Depth Anything raw predictions are normalized into the contract unit `relative_0_near_1_far` before publishing or logging. Downstream gates should treat lower center-band values as closer/blocked and higher values as farther/clearer.
- Navigation on `5558`: JSON high-level action from the allowed action set. Cooper maps that action to drone commands.
- Health on `5559`: JSON pipeline status, model state, throughput, memory, and errors.

## Modes

- `stub`: no model weights required. Publishes deterministic demo-safe detections, depth, navigation, and health.
- `detector-only`: attempts the lazy detector placeholder and falls back safely for unavailable model dependencies.
- `models`: attempts lazy model placeholders for detection, depth, and navigation. Missing imports or weights are reported on health and replaced with safe fallbacks.

Fallback behavior must preserve the output contracts. Navigation falls back to `hover` or conservative rule-based actions when model output is unavailable or invalid.

Current executable real-model fallback:

- Primary navigation VLM:
  - `BREACHEYE_QWEN_MODEL=models/qwen3-vl-2b/Qwen3-VL-2B-Instruct-Q4_K_M.gguf`
  - `BREACHEYE_QWEN_MMPROJ=models/qwen3-vl-2b/mmproj-F16.gguf`
  - requires `llama-mtmd-cli` from `brew install llama.cpp`
  - preferred speed path: run `llama-server` and set `BREACHEYE_QWEN_SERVER_URL`
- `BREACHEYE_SMOLVLM_PATH=models/smolvlm2-500m`
- `BREACHEYE_SMOLVLM_DEVICE=cpu`
- preferred depth path:
  - `BREACHEYE_DEPTH_ANYTHING_PATH=models/depth-anything-v2-small-hf`
  - optional `BREACHEYE_DEPTH_ANYTHING_DEVICE=mps`
- `breacheye rafa --mode models`

Qwen3-VL-2B is the preferred keyframe navigation model. SmolVLM2-500M is a slower CPU fallback and should not be used for every-frame control.

## Model Readiness

Model weights are local runtime artifacts and are not committed. Check the current machine with:

```bash
breacheye rafa doctor
breacheye rafa doctor --require-models
```

The real model path environment variables are:

- `BREACHEYE_MOONDREAM_WEIGHTS`
- `BREACHEYE_DEPTH_ANYTHING_PATH`
- `BREACHEYE_QWEN_MODEL`
- `BREACHEYE_QWEN_MMPROJ` when using a GGUF vision projector
- `BREACHEYE_SMOLVLM_PATH` for the slow CPU Transformers fallback

`--require-models` exits non-zero until model packages and local weights are available. `stub` mode remains the required demo fallback.

The current first target for navigation reasoning is documented in `docs/rafa-model-options.md`.
