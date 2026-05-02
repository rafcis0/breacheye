from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

from PIL import Image


PROMPT_SIDE = 720


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark local monocular depth models.")
    parser.add_argument("--runtime", choices=["depth-pro", "depth-anything-hf"], required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--image", default="demo/generated/sample-indoor-frame.jpg")
    parser.add_argument("--device", default="mps")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--output")
    args = parser.parse_args()

    image = Image.open(args.image).convert("RGB")
    image.thumbnail((PROMPT_SIDE, PROMPT_SIDE))

    if args.runtime == "depth-pro":
        benchmark = benchmark_depth_pro(args.model_path, image, args.device, args.warmup, args.runs)
    else:
        benchmark = benchmark_depth_anything_hf(args.model_path, image, args.device, args.warmup, args.runs)

    benchmark.update(
        {
            "runtime": args.runtime,
            "model_path": args.model_path,
            "image": args.image,
            "image_size": list(image.size),
            "device": args.device,
        }
    )
    text = json.dumps(benchmark, indent=2, sort_keys=True)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    print(text)


def benchmark_depth_pro(model_path: str, image: Image.Image, device_name: str, warmup: int, runs: int) -> dict[str, Any]:
    import numpy as np
    import torch
    import depth_pro
    from depth_pro.depth_pro import DEFAULT_MONODEPTH_CONFIG_DICT
    from dataclasses import replace

    device = torch.device(device_name if device_name != "mps" or torch.backends.mps.is_available() else "cpu")
    started = time.perf_counter()
    config = replace(DEFAULT_MONODEPTH_CONFIG_DICT, checkpoint_uri=model_path)
    model, transform = depth_pro.create_model_and_transforms(config=config, device=device)
    model.eval()
    image_tensor = transform(image).to(device)
    load_s = time.perf_counter() - started

    def infer() -> tuple[float, tuple[int, ...]]:
        if device.type == "mps":
            torch.mps.synchronize()
        start = time.perf_counter()
        with torch.inference_mode():
            prediction = model.infer(image_tensor, f_px=None)
            depth = prediction["depth"].detach().float().cpu().numpy()
        if device.type == "mps":
            torch.mps.synchronize()
        return time.perf_counter() - start, tuple(int(v) for v in depth.shape)

    for _ in range(warmup):
        infer()
    times: list[float] = []
    shape: tuple[int, ...] = ()
    for _ in range(runs):
        elapsed, shape = infer()
        times.append(elapsed)
    return _stats(load_s, times, {"depth_shape": list(shape), "numpy": np.__version__})


def benchmark_depth_anything_hf(model_path: str, image: Image.Image, device_name: str, warmup: int, runs: int) -> dict[str, Any]:
    import torch
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation

    device = torch.device(device_name if device_name != "mps" or torch.backends.mps.is_available() else "cpu")
    started = time.perf_counter()
    processor = AutoImageProcessor.from_pretrained(model_path)
    model = AutoModelForDepthEstimation.from_pretrained(model_path).to(device)
    model.eval()
    inputs = processor(images=image, return_tensors="pt")
    inputs = {key: value.to(device) for key, value in inputs.items()}
    load_s = time.perf_counter() - started

    def infer() -> tuple[float, tuple[int, ...]]:
        if device.type == "mps":
            torch.mps.synchronize()
        start = time.perf_counter()
        with torch.inference_mode():
            outputs = model(**inputs)
            depth = outputs.predicted_depth.detach().float().cpu()
        if device.type == "mps":
            torch.mps.synchronize()
        return time.perf_counter() - start, tuple(int(v) for v in depth.shape)

    for _ in range(warmup):
        infer()
    times: list[float] = []
    shape: tuple[int, ...] = ()
    for _ in range(runs):
        elapsed, shape = infer()
        times.append(elapsed)
    return _stats(load_s, times, {"depth_shape": list(shape)})


def _stats(load_s: float, times: list[float], extra: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "load_s": load_s,
        "runs_s": times,
        "mean_s": statistics.mean(times),
        "median_s": statistics.median(times),
        "min_s": min(times),
        "max_s": max(times),
        "fps_mean": 1.0 / statistics.mean(times),
    }
    result.update(extra)
    return result


if __name__ == "__main__":
    main()
