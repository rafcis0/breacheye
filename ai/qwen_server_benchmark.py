from __future__ import annotations

import argparse
import base64
import json
import time
import urllib.request
from pathlib import Path


PROMPT = (
    "Return only compact JSON with keys action, confidence, reasoning. "
    "Allowed action values: hover, move_forward, rotate_left, rotate_right. "
    "If uncertain, choose hover. No markdown."
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark warm Qwen3-VL llama-server navigation calls.")
    parser.add_argument("--server-url", default="http://127.0.0.1:56262")
    parser.add_argument("--image", type=Path, default=Path("demo/generated/sample-indoor-frame.jpg"))
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=32)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cache-bust", action="store_true", help="Append run id text to the prompt so server cache cannot reuse the full request.")
    args = parser.parse_args()

    image_b64 = base64.b64encode(args.image.read_bytes()).decode("ascii")
    timings = []
    outputs = []
    for index in range(args.warmup + args.runs):
        prompt = PROMPT
        if args.cache_bust:
            prompt = f"{prompt} Request id: {time.time_ns()}."
        started = time.perf_counter()
        output = call_server(args.server_url, image_b64, prompt, args.max_tokens)
        elapsed = time.perf_counter() - started
        if index >= args.warmup:
            timings.append(elapsed)
            outputs.append(output)
            print(f"run={index - args.warmup} elapsed_s={elapsed:.4f} output={output[:160]!r}")
        else:
            print(f"warmup={index} elapsed_s={elapsed:.4f}")

    result = {
        "server_url": args.server_url,
        "image": str(args.image),
        "runs": args.runs,
        "warmup": args.warmup,
        "max_tokens": args.max_tokens,
        "cache_bust": args.cache_bust,
        "timings_s": timings,
        "mean_s": sum(timings) / len(timings) if timings else None,
        "min_s": min(timings) if timings else None,
        "max_s": max(timings) if timings else None,
        "outputs": outputs,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("mean_s", "min_s", "max_s")}, sort_keys=True))


def call_server(server_url: str, image_b64: str, prompt: str, max_tokens: int) -> str:
    payload = {
        "model": "gpt-4-vision",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                ],
            }
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    request = urllib.request.Request(
        server_url.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


if __name__ == "__main__":
    main()
