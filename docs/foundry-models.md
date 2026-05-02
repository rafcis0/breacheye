# Foundry Model Inventory

Tested 2026-05-02. Instance: mcande21.euw-3.palantirfoundry.co.uk

## Available Models

### Anthropic

| Model | Alias | Use For |
|-------|-------|---------|
| Claude Sonnet 4.6 | claude-sonnet-4-6 | AIP Chatbot (recommended), tactical queries |
| Claude Opus 4.6 | claude-opus-4-6 | Complex reasoning, heavy analysis |
| Claude Haiku 4.5 | claude-haiku-4-5 | High-volume, low-latency |

Proxy: `POST /api/v2/llm/proxy/anthropic/v1/messages`
Parameter: `max_tokens`

### OpenAI

| Model | Alias | Use For |
|-------|-------|---------|
| GPT-5.4 | gpt-5.4 | Flagship reasoning |
| GPT-4o | gpt-4o | Multi-modal (vision capable) |
| GPT-4.1 | gpt-4.1 | Structured output, tool calling |
| GPT-4.1 Mini | gpt-4.1-mini | Fast structured output |
| GPT-4.1 Nano | gpt-4.1-nano | Ultra-fast, cheapest |
| o3 | o3 | Deep reasoning chains |
| o4-mini | o4-mini | Reasoning at lower cost |

Proxy: `POST /api/v2/llm/proxy/openai/v1/chat/completions`
Parameter: `max_completion_tokens` (NOT `max_tokens` for gpt-5.4, o3, o4-mini)

### Not Available

- Google Gemini (all variants) — proxy path may differ or not enabled
- Claude 3.x family (deprecated aliases)
- GPT-4o-mini, o3-mini

## Recommendations

- **AIP Chatbot:** Claude Sonnet 4.6, temperature 0
- **Vision analysis (if proxy supports images):** GPT-4o
- **High-volume batch:** Claude Haiku 4.5 or GPT-4.1 Nano
- **Complex tactical reasoning:** Claude Opus 4.6 or o3

## Auth

All calls require: `Authorization: Bearer $FOUNDRY_TOKEN`
Token and host configured in `.env` (gitignored).
