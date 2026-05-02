#!/usr/bin/env bash
set -euo pipefail

mkdir -p models/qwen3-vl-2b models/qwen3-vl-4b models/smolvlm2-500m models/internvl3-1b models/qwen2.5-vl-3b-bnb4bit

hf download unsloth/Qwen3-VL-2B-Instruct-GGUF \
  Qwen3-VL-2B-Instruct-Q4_K_M.gguf mmproj-F16.gguf \
  --local-dir models/qwen3-vl-2b

hf download HuggingFaceTB/SmolVLM2-500M-Video-Instruct \
  --include '*.json' '*.safetensors' '*.txt' 'tokenizer*' 'vocab*' 'merges*' \
  --exclude 'onnx/*' \
  --local-dir models/smolvlm2-500m

hf download OpenGVLab/InternVL3-1B \
  --local-dir models/internvl3-1b

hf download unsloth/Qwen2.5-VL-3B-Instruct-unsloth-bnb-4bit \
  --local-dir models/qwen2.5-vl-3b-bnb4bit

hf download unsloth/Qwen3-VL-4B-Instruct-GGUF \
  Qwen3-VL-4B-Instruct-Q4_K_M.gguf mmproj-F16.gguf \
  --local-dir models/qwen3-vl-4b
