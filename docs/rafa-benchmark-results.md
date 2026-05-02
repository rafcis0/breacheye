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
| `unsloth/Qwen3-VL-2B-Instruct-GGUF` | Partial cache only | Blocked until GGUF VLM runtime is installed | First target. Hotspot retry started but stalled before usable files landed. Needs `.gguf` model plus `mmproj-F16.gguf`/`mmproj-BF16.gguf`. |
| `HuggingFaceTB/SmolVLM2-500M-Video-Instruct` | Config/tokenizer downloaded; model weights stalled before first byte | Pending | Smallest practical Transformers fallback. Broad snapshot tried first, then single-file `model.safetensors`; both stalled on the large weight file. |
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

Keep `stub` mode as the only fully locked demo path until at least one real VLM produces valid navigation JSON from `ai/model_benchmark.py`.

The first real model target remains `unsloth/Qwen3-VL-2B-Instruct-GGUF`; the first fallback to actually execute through Transformers is `HuggingFaceTB/SmolVLM2-500M-Video-Instruct`.

## Next Download Attempts

If Hugging Face large-file downloads keep stalling:

1. Retry from a stronger network with `HF_HUB_ENABLE_HF_TRANSFER=1` after installing `huggingface_hub[hf_transfer]`.
2. Prefer single-file includes over full snapshots so ONNX artifacts are not pulled accidentally.
3. Download `SmolVLM2-500M` first because it can be benchmarked through the installed Transformers runtime.
4. Install a GGUF multimodal runtime before spending more time on Qwen GGUF benchmarking.
