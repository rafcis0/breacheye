# Rafa Benchmark Results

Benchmark date: 2026-05-02.

Hardware: local Mac, Apple Silicon environment. Exact Torch/MPS availability is captured by `ai/model_benchmark.py` outputs.

## Commands

Download candidates:

```bash
ai/download_models.sh
```

Benchmark a Transformers model:

```bash
python ai/model_benchmark.py \
  --model-id HuggingFaceTB/SmolVLM2-500M-Video-Instruct \
  --model-path models/smolvlm2-500m \
  --runtime transformers \
  --runs 1 \
  --output demo/benchmarks/smolvlm2-500m.json
```

Record a GGUF runtime blocker until llama.cpp multimodal support is installed:

```bash
python ai/model_benchmark.py \
  --model-id unsloth/Qwen3-VL-2B-Instruct-GGUF \
  --model-path models/qwen3-vl-2b/Qwen3-VL-2B-Instruct-Q4_K_M.gguf \
  --runtime gguf \
  --output demo/benchmarks/qwen3-vl-2b-gguf.json
```

## Current Results

| Model | Download status | Benchmark status | Notes |
|-------|-----------------|------------------|-------|
| `unsloth/Qwen3-VL-2B-Instruct-GGUF` | Downloaded from `~/Downloads` into ignored `models/qwen3-vl-2b/` | GGUF OK through `llama-mtmd-cli`; faster through warm `llama-server` | First target. Local files present: `Qwen3-VL-2B-Instruct-Q4_K_M.gguf` and `mmproj-F16.gguf`. CLI benchmark wall `3.12s`; llama internal total `2.27s`; warm server calls were `0.24-0.79s` on cached prompt/image and model-mode server smoke emitted valid nav `hover` in about `2.0s`. |
| `HuggingFaceTB/SmolVLM2-500M-Video-Instruct` | Downloaded from `~/Downloads` plus HF configs into ignored `models/smolvlm2-500m/` | CPU OK; MPS failed | CPU load `4.29s`, first run `6.05s`, output `rotate_right`. Model-mode ZMQ smoke emitted valid nav `rotate_left`. MPS crashed with incompatible matmul shapes. |
| `moondream/moondream-2b-2025-04-14-4bit` | Downloaded | GGUF CPU OK but slow; Metal assertion | Use only as a fallback/research detector. CPU total was `13.94s`; output was not strict JSON. |
| `depth-anything/Depth-Anything-V2-Small-hf` | Downloaded into ignored `models/depth-anything-v2-small-hf/` | MPS OK | Mean `0.0406s`, about `24.6 FPS`, output shape `1x518x686`. Keep this for depth. |
| `apple/FastVLM-0.5B` / `apple/ml-fastvlm` | Partial; safetensors still needed | Pending | Best speed experiment for Apple Silicon. HF checkpoint is about 1.53 GB; Apple's repo also provides Apple Silicon export/runtime paths. |
| `apple/ml-depth-pro` | Repo cloned; checkpoint intentionally stopped | Deferred | Interesting for metric depth later, but Depth Anything is already fast enough. |
| `OpenGVLab/InternVL3-1B` | Pending | Pending | Small HF alternative; may need `trust_remote_code`. |
| `unsloth/Qwen2.5-VL-3B-Instruct-unsloth-bnb-4bit` | Pending | Pending | bnb 4-bit may be less Mac-friendly. |
| `unsloth/Qwen3-VL-4B-Instruct-GGUF` | Pending | Blocked until GGUF VLM runtime is installed | Capability fallback if 2B fails quality. |

## Selection Criteria

Use a model only if it can:

- Accept a single 960x720-ish indoor frame or resized equivalent.
- Return strict JSON with an allowed navigation action.
- Stay within a demo-safe latency budget for keyframes, ideally under 3 seconds and no worse than 5 seconds.
- Run locally without destabilizing the Tello safety harness.

## Current Decision

Keep `stub` mode as the safest demo path. `SmolVLM2-500M` is now a slow CPU fallback candidate for keyframes, not every-frame control.

The first real model target is now executable: `unsloth/Qwen3-VL-2B-Instruct-GGUF` through Homebrew `llama.cpp` / `llama-mtmd-cli`.

The fallback remains `HuggingFaceTB/SmolVLM2-500M-Video-Instruct` through CPU Transformers.

## Smoke Results

Stub cross-process:

- `breacheye rafa --mode stub`
- `python integration/frame_publisher.py --frames 3 --fps 5`
- Logs created under `logs/<run_id>-rafa.jsonl` and `logs/<run_id>-frame_publisher.jsonl`

SmolVLM model-mode cross-process:

- `BREACHEYE_SMOLVLM_PATH=models/smolvlm2-500m`
- `BREACHEYE_SMOLVLM_DEVICE=cpu`
- `breacheye rafa --mode models`
- one synthetic frame through `integration/frame_publisher.py`
- received navigation action: `rotate_left`
- logs created for both processes

Qwen model-mode cross-process:

- `BREACHEYE_QWEN_MODEL=models/qwen3-vl-2b/Qwen3-VL-2B-Instruct-Q4_K_M.gguf`
- `BREACHEYE_QWEN_MMPROJ=models/qwen3-vl-2b/mmproj-F16.gguf`
- `breacheye rafa --mode models`
- continuous synthetic frames through `integration/frame_publisher.py`
- received navigation action: `hover`
- logs created for both processes

Qwen server mode:

```bash
llama-server \
  -m models/qwen3-vl-2b/Qwen3-VL-2B-Instruct-Q4_K_M.gguf \
  --mmproj models/qwen3-vl-2b/mmproj-F16.gguf \
  --host 127.0.0.1 --port 56262 \
  --ctx-size 4096 -ngl 99

export BREACHEYE_QWEN_SERVER_URL=http://127.0.0.1:56262
export BREACHEYE_QWEN_MAX_TOKENS=32
breacheye rafa --mode models
```

This keeps Qwen loaded on Metal and avoids per-keyframe process/model startup.

Moondream detection benchmark:

```bash
llama-mtmd-cli \
  -m models/moondream-gguf/moondream2-text-model-f16.gguf \
  --mmproj models/moondream-gguf/moondream2-mmproj-f16.gguf \
  --image demo/generated/sample-indoor-frame.jpg \
  -p "Detect tactical objects or hazards in this indoor frame. Return compact JSON." \
  -n 96 --temp 0
```

Observed result on 2026-05-02:

- Metal path loaded then hit a llama.cpp Metal assertion.
- CPU-only path with `--chat-template vicuna --no-mmproj-offload --no-warmup -ngl 0` completed.
- Total time was `13.94s`, with image encoding/decoding around `10.1s`; this is too slow for the inner loop.
- Output was a plain natural-language answer, not strict JSON.

FastVLM first benchmark:

```bash
hf download apple/FastVLM-0.5B --local-dir models/fastvlm-0.5b
git clone https://github.com/apple/ml-fastvlm research/ml-fastvlm
cd research/ml-fastvlm
python -m pip install -e .
python predict.py \
  --model-path ../../models/fastvlm-0.5b \
  --image-file ../../demo/generated/sample-indoor-frame.jpg \
  --prompt "Return only compact JSON with keys action, confidence, reasoning. Allowed actions: hover, move_forward, rotate_left, rotate_right."
```

Depth Anything V2 Small benchmark:

```bash
python ai/depth_benchmark.py \
  --runtime depth-anything-hf \
  --model-path models/depth-anything-v2-small-hf \
  --image demo/generated/sample-indoor-frame.jpg \
  --device mps \
  --warmup 2 \
  --runs 5
```

## Local Environment

```bash
export BREACHEYE_QWEN_MODEL=models/qwen3-vl-2b/Qwen3-VL-2B-Instruct-Q4_K_M.gguf
export BREACHEYE_QWEN_MMPROJ=models/qwen3-vl-2b/mmproj-F16.gguf
export BREACHEYE_SMOLVLM_PATH=models/smolvlm2-500m
export BREACHEYE_SMOLVLM_DEVICE=cpu
export BREACHEYE_DEPTH_ANYTHING_PATH=models/depth-anything-v2-small-hf
export BREACHEYE_DEPTH_ANYTHING_DEVICE=mps
```

## Next Download Attempts

If Hugging Face large-file downloads keep stalling:

1. Retry from a stronger network with `HF_HUB_ENABLE_HF_TRANSFER=1` after installing `huggingface_hub[hf_transfer]`.
2. Prefer single-file includes over full snapshots so ONNX artifacts are not pulled accidentally.
3. Download `FastVLM-0.5B` next because it is the strongest speed candidate for this Mac path.
4. Keep Qwen server mode as the live demo path until FastVLM proves faster end-to-end.
