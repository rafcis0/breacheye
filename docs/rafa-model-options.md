# Rafa Model Options

Current decision: use `unsloth/Qwen3-VL-2B-Instruct-GGUF` as the first real navigation VLM target because it already runs through `llama.cpp`. Treat `apple/FastVLM-0.5B` as the next speed experiment for Apple Silicon.

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
6. Benchmark FastVLM-0.5B as the likely fastest Apple Silicon option after Qwen is stable.
7. If Qwen fails at runtime, fall back to `HuggingFaceTB/SmolVLM2-500M-Video-Instruct` on CPU.

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

## Current Local State

As of the latest readiness check:

- Qwen3-VL-2B GGUF and projector are present locally.
- SmolVLM2-500M is present locally.
- Moondream projector is present locally; text GGUF download is in progress.
- FastVLM is not downloaded yet.
- No Depth Anything V2 weights found.
- Ollama has `qwen3.6:35b-a3b-q4_K_M` and `gemma4:26b`.
- No Ollama Qwen VL model found.

That means model mode can only run through safe fallbacks until weights/deps are installed.
