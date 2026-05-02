from __future__ import annotations

import argparse
import json
import platform
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


DEFAULT_PROMPT = (
    "You are controlling an indoor drone. Return compact JSON with keys "
    "action, confidence, reasoning. Choose one of hover, move_forward, "
    "rotate_left, rotate_right. What should the drone do next?"
)


@dataclass
class BenchmarkResult:
    model_id: str
    model_path: str
    runtime: str
    status: str
    load_s: float | None = None
    first_run_s: float | None = None
    avg_run_s: float | None = None
    output_preview: str | None = None
    error: str | None = None
    notes: str | None = None


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark local VLM candidates for BreachEye.")
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--runtime", choices=["transformers", "gguf"], required=True)
    parser.add_argument("--image", type=Path)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--max-new-tokens", type=int, default=96)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    image = args.image or _make_sample_image()
    if args.runtime == "gguf":
        result = BenchmarkResult(
            model_id=args.model_id,
            model_path=args.model_path,
            runtime=args.runtime,
            status="blocked",
            notes="GGUF VLM benchmark needs a llama.cpp multimodal runtime with projector support.",
        )
    else:
        result = benchmark_transformers(
            model_id=args.model_id,
            model_path=args.model_path,
            image=image,
            runs=args.runs,
            max_new_tokens=args.max_new_tokens,
        )
    payload = {"system": _system_info(), "result": asdict(result)}
    text = json.dumps(payload, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")
    print(text)


def benchmark_transformers(
    model_id: str,
    model_path: str,
    image: Path,
    runs: int,
    max_new_tokens: int,
) -> BenchmarkResult:
    started = time.perf_counter()
    try:
        import torch
        from PIL import Image
        from transformers import AutoModelForImageTextToText, AutoProcessor

        device = _torch_device(torch)
        dtype = torch.float16 if device == "mps" else torch.float32
        processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True)
        model = AutoModelForImageTextToText.from_pretrained(
            model_path,
            torch_dtype=dtype,
            trust_remote_code=True,
            low_cpu_mem_usage=True,
        )
        model.to(device)
        model.eval()
        load_s = time.perf_counter() - started
        pil_image = Image.open(image).convert("RGB")
        timings: list[float] = []
        output_preview = ""
        for _ in range(max(1, runs)):
            run_started = time.perf_counter()
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": pil_image},
                        {"type": "text", "text": DEFAULT_PROMPT},
                    ],
                }
            ]
            inputs = processor.apply_chat_template(
                messages,
                add_generation_prompt=True,
                tokenize=True,
                return_dict=True,
                return_tensors="pt",
            )
            inputs = {key: value.to(device) for key, value in inputs.items()}
            with torch.inference_mode():
                generated = model.generate(**inputs, do_sample=False, max_new_tokens=max_new_tokens)
            output_preview = processor.batch_decode(generated, skip_special_tokens=True)[0][-500:]
            timings.append(time.perf_counter() - run_started)
        return BenchmarkResult(
            model_id=model_id,
            model_path=model_path,
            runtime="transformers",
            status="ok",
            load_s=load_s,
            first_run_s=timings[0],
            avg_run_s=statistics.mean(timings),
            output_preview=output_preview,
        )
    except Exception as exc:
        return BenchmarkResult(
            model_id=model_id,
            model_path=model_path,
            runtime="transformers",
            status="failed",
            error=repr(exc),
        )


def _make_sample_image() -> Path:
    import cv2
    import numpy as np

    path = Path("demo/generated/sample-indoor-frame.jpg")
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = np.zeros((720, 960, 3), dtype=np.uint8)
    frame[:, :] = (28, 30, 34)
    cv2.rectangle(frame, (100, 180), (280, 620), (92, 120, 155), -1)
    cv2.rectangle(frame, (460, 220), (850, 620), (68, 88, 105), -1)
    cv2.line(frame, (0, 650), (960, 650), (190, 190, 190), 3)
    cv2.putText(frame, "mock indoor corridor", (60, 90), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (230, 230, 230), 2)
    cv2.imwrite(str(path), frame)
    return path


def _torch_device(torch_module: Any) -> str:
    if getattr(torch_module.backends, "mps", None) and torch_module.backends.mps.is_available():
        return "mps"
    if torch_module.cuda.is_available():
        return "cuda"
    return "cpu"


def _system_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "platform": platform.platform(),
        "python": platform.python_version(),
    }
    try:
        import torch

        info["torch"] = torch.__version__
        info["mps_available"] = bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())
        info["cuda_available"] = torch.cuda.is_available()
    except Exception:
        pass
    return info


if __name__ == "__main__":
    main()
