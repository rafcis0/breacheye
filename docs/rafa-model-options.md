# Rafa Model Options

Current decision: use `unsloth/Qwen3-VL-2B-Instruct-GGUF` as the first real navigation VLM target, with `HuggingFaceTB/SmolVLM2-500M-Video-Instruct` as the smallest practical fallback if Qwen fails at runtime.

Do not commit weights. Download them into ignored local paths such as `models/` or `weights/`, then point the pipeline at them with environment variables.

## Top 5 Options

| Rank | Model | Source | Why it matters | Tradeoff |
|------|-------|--------|----------------|----------|
| 1 | `unsloth/Qwen3-VL-2B-Instruct-GGUF` | Unsloth / HF | Best fit for our app: real Qwen VL family, Apache-2.0, GGUF quantizations, small enough for local testing. Q4 variants are around 1.0-1.1 GB plus the vision projector. | Needs a GGUF vision runtime path wired into our adapter. |
| 2 | `HuggingFaceTB/SmolVLM2-500M-Video-Instruct` | Hugging Face | Smallest option I would seriously try for live video/frame reasoning. HF says it needs about 1.8 GB GPU RAM for video inference and supports image/video/text tasks. | Less spatial/reasoning headroom than Qwen; may need stricter prompts and rule-based guardrails. |
| 3 | `OpenGVLab/InternVL3-1B` | Hugging Face | Very small multimodal model, Apache/MIT-compatible components, explicit spatial/GUI/multimodal capabilities. | Uses custom code/trust-remote-code path and may be less convenient on Apple Silicon. |
| 4 | `unsloth/Qwen2.5-VL-3B-Instruct-unsloth-bnb-4bit` | Unsloth / HF | Older but proven Qwen VL family. The card includes agent/mobile-control benchmark data, which is close to our navigation-decision use case. | More parameters than Qwen3-VL-2B; bnb 4-bit is less Mac-friendly than GGUF. |
| 5 | `unsloth/Qwen3-VL-4B-Instruct-GGUF` | Unsloth / HF | Better capability reserve than 2B; Q4 variants are roughly 2.3-2.5 GB plus projector. | Not the smallest. Use only if 2B/500M fail task quality. |

## Recommendation

Lock this sequence for Rafa's side:

1. Keep `stub` as the demo-safe fallback.
2. Use the Qwen adapter against `unsloth/Qwen3-VL-2B-Instruct-GGUF`.
3. Use `Qwen3-VL-2B-Instruct-Q4_K_M.gguf` first.
4. Use the matching `mmproj-F16.gguf` projector.
5. If Qwen fails at runtime, fall back to `HuggingFaceTB/SmolVLM2-500M-Video-Instruct` on CPU.

Expected local environment:

```bash
export BREACHEYE_QWEN_MODEL="models/qwen3-vl-2b/Qwen3-VL-2B-Instruct-Q4_K_M.gguf"
export BREACHEYE_QWEN_MMPROJ="models/qwen3-vl-2b/mmproj-F16.gguf"
```

Then:

```bash
breacheye rafa doctor --require-models
```

## Current Local State

As of the latest readiness check:

- No Moondream weights found.
- No Depth Anything V2 weights found.
- Ollama has `qwen3.6:35b-a3b-q4_K_M` and `gemma4:26b`.
- No Ollama Qwen VL model found.

That means model mode can only run through safe fallbacks until weights/deps are installed.
