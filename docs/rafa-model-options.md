# Rafa Model Options

Current decision: use `unsloth/Qwen3-VL-2B-Instruct-GGUF` as the working navigation VLM target because it already runs through `llama.cpp`. Keep `Depth-Anything-V2-Small-hf` for fast depth and benchmark `apple/FastVLM-0.5B` as the next VLM speed lane.

Do not commit weights. Download them into ignored local paths such as `models/` or `weights/`, then point the pipeline at them with environment variables.

## Top 5 Options

| Rank | Model | Source | Why it matters | Tradeoff |
|------|-------|--------|----------------|----------|
| 1 | `unsloth/Qwen3-VL-2B-Instruct-GGUF` | Unsloth / HF | Current working model. Real Qwen VL family, Apache-2.0, GGUF quantization, small enough for local testing. Q4 model is about 1.0 GB plus projector. | Good keyframe latency, but still not every-frame control. |
| 2 | `apple/FastVLM-0.5B` / `apple/ml-fastvlm` | Apple / HF | Best speed experiment. Apple reports the smallest variant has much faster TTFT than comparable small VLMs and provides Apple Silicon export/runtime paths. HF has a 1.53 GB 0.5B checkpoint. | Needs separate setup/export path and model license review before demo use. |
| 3 | `HuggingFaceTB/SmolVLM2-500M-Video-Instruct` | Hugging Face | Smallest fallback that already runs locally through Transformers CPU. | ~6s CPU inference in our benchmark; MPS crashed on attention shape. |
| 4 | `OpenGVLab/InternVL3-1B` | Hugging Face | Very small multimodal model, Apache/MIT-compatible components, explicit spatial/GUI/multimodal capabilities. | Uses custom code/trust-remote-code path and may be less convenient on Apple Silicon. |
| 5 | `unsloth/Qwen2.5-VL-3B-Instruct-unsloth-bnb-4bit` | Unsloth / HF | Older but proven Qwen VL family. The card includes agent/mobile-control benchmark data, close to our navigation-decision use case. | More parameters than Qwen3-VL-2B; bnb 4-bit is less Mac-friendly than GGUF. |

## Recommendation

Lock this sequence for Rafa's side:

1. Keep `stub` as the demo-safe fallback.
2. Use the Qwen adapter against `unsloth/Qwen3-VL-2B-Instruct-GGUF`.
3. Use `Qwen3-VL-2B-Instruct-Q4_K_M.gguf` first.
4. Use the matching `mmproj-F16.gguf` projector.
5. Keep Qwen loaded with `llama-server` for warm keyframe calls.
6. Benchmark FastVLM-0.5B as the likely fastest Apple Silicon VLM option.
7. Use `depth-anything/Depth-Anything-V2-Small-hf` for the real depth estimator.
8. If Qwen/FastVLM fail at runtime, fall back to `HuggingFaceTB/SmolVLM2-500M-Video-Instruct` on CPU.

Expected local environment:

```bash
export BREACHEYE_QWEN_MODEL="models/qwen3-vl-2b/Qwen3-VL-2B-Instruct-Q4_K_M.gguf"
export BREACHEYE_QWEN_MMPROJ="models/qwen3-vl-2b/mmproj-F16.gguf"
```

Then:

```bash
breacheye rafa doctor --require-models
```

## FastVLM Note

Apple's FastVLM repo is worth a separate benchmark lane. The repository describes FastViTHD, a hybrid vision encoder that outputs fewer image tokens and significantly reduces high-resolution image encoding time. It also provides Apple Silicon compatible models and export instructions. This is likely the best path if Qwen3-VL-2B is too slow for keyframes.

Initial FastVLM target:

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

Do this in `research/` and `models/`; both should stay ignored. If the PyTorch path is too slow or unstable, use Apple's export path from `model_export/` instead of trying to force it through the existing Qwen GGUF adapter.

## Depth Note

Depth Anything V2 Small is the depth path for now. It benchmarked at about `0.041s` per frame on MPS on the sample frame, which is fast enough for the inner loop. Depth Pro is still interesting for metric depth later, but its checkpoint is large and not needed for this demo path.

## Current Local State

As of the latest readiness check:

- Qwen3-VL-2B GGUF and projector are present locally.
- SmolVLM2-500M is present locally.
- Moondream GGUF text model and projector are present locally, but the tested GGUF path is too slow for the inner loop.
- FastVLM metadata is present locally; `model.safetensors` is still a partial download and must reach `1,517,793,184` bytes before benchmarking.
- Depth Anything V2 Small is present locally in `models/depth-anything-v2-small-hf`.
- Depth Pro repo is cloned under ignored `research/ml-depth-pro`; checkpoint download was intentionally stopped.
- Ollama has `qwen3.6:35b-a3b-q4_K_M` and `gemma4:26b`.
- No Ollama Qwen VL model found.

That means the current locked local stack is Qwen server navigation plus Depth Anything depth. FastVLM is still a benchmark candidate, not a dependency for the demo path.
