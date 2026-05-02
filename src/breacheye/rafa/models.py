from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
from typing import Any
import base64
import json
import urllib.request

from breacheye.rafa.adapters import DetectionAdapter, DepthAdapter, NavigationAdapter
from breacheye.rafa.schemas import DepthOutput, DetectionOutput, FrameInput, NavigationDecision, NavigationOutput


class ModelUnavailable(RuntimeError):
    pass


class LazyMoondreamDetector(DetectionAdapter):
    name = "moondream"

    def __init__(self) -> None:
        try:
            import moondream  # noqa: F401
        except ImportError as exc:
            raise ModelUnavailable("moondream package is not installed") from exc
        raise ModelUnavailable("moondream weights are not configured")

    async def detect(self, frame: Any, meta: FrameInput) -> DetectionOutput:
        raise ModelUnavailable("moondream detector is unavailable")


class LazyDepthAnythingV2Estimator(DepthAdapter):
    name = "depth_anything_v2"

    def __init__(self) -> None:
        self.model_path = os.environ.get("BREACHEYE_DEPTH_ANYTHING_PATH") or os.environ.get("BREACHEYE_DEPTH_ANYTHING_WEIGHTS")
        if not self.model_path:
            raise ModelUnavailable("BREACHEYE_DEPTH_ANYTHING_PATH is not set")
        if not os.path.exists(self.model_path):
            raise ModelUnavailable(f"Depth Anything V2 path does not exist: {self.model_path}")
        try:
            import torch
            from transformers import AutoImageProcessor, AutoModelForDepthEstimation
        except ImportError as exc:
            raise ModelUnavailable("transformers and torch are required for Depth Anything V2") from exc
        self.torch = torch
        requested_device = os.environ.get("BREACHEYE_DEPTH_ANYTHING_DEVICE")
        if requested_device:
            self.device = torch.device(requested_device)
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            self.device = torch.device("mps")
        else:
            self.device = torch.device("cpu")
        self.processor = AutoImageProcessor.from_pretrained(self.model_path)
        self.model = AutoModelForDepthEstimation.from_pretrained(self.model_path).to(self.device)
        self.model.eval()

    async def estimate(self, frame: Any, meta: FrameInput) -> DepthOutput:
        import asyncio

        return await asyncio.to_thread(self._estimate_sync, frame, meta)

    def _estimate_sync(self, frame: Any, meta: FrameInput) -> DepthOutput:
        import numpy as np
        from PIL import Image

        image = Image.fromarray(_bgr_to_rgb(frame))
        inputs = self.processor(images=image, return_tensors="pt")
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with self.torch.inference_mode():
            output = self.model(**inputs)
            depth = output.predicted_depth.detach().float().cpu().squeeze().numpy()
        finite = np.isfinite(depth)
        if finite.any():
            near = float(np.nanpercentile(depth[finite], 2))
            far = float(np.nanpercentile(depth[finite], 98))
            denom = max(far - near, 1e-6)
            relative = np.clip((depth - near) / denom, 0.0, 1.0).astype(np.float32)
        else:
            relative = np.ones_like(depth, dtype=np.float32)
        return DepthOutput(
            frame_id=meta.frame_id,
            timestamp=time.time(),
            shape=relative.shape,
            depth_bytes=relative.tobytes(),
        )


class LazyQwen3VLNavigator(NavigationAdapter):
    name = "qwen3_vl"

    def __init__(self) -> None:
        self.model_path = os.environ.get("BREACHEYE_QWEN_MODEL")
        self.mmproj_path = os.environ.get("BREACHEYE_QWEN_MMPROJ")
        self.binary = os.environ.get("BREACHEYE_LLAMA_MTMD", "llama-mtmd-cli")
        self.server_url = os.environ.get("BREACHEYE_QWEN_SERVER_URL")
        if not self.model_path:
            raise ModelUnavailable("BREACHEYE_QWEN_MODEL is not set")
        if not self.mmproj_path:
            raise ModelUnavailable("BREACHEYE_QWEN_MMPROJ is not set")
        if not os.path.exists(self.model_path):
            raise ModelUnavailable(f"Qwen model path does not exist: {self.model_path}")
        if not os.path.exists(self.mmproj_path):
            raise ModelUnavailable(f"Qwen mmproj path does not exist: {self.mmproj_path}")
        if not self.server_url and not _binary_available(self.binary):
            raise ModelUnavailable(f"{self.binary} is not installed")

    async def decide(
        self,
        frame: Any,
        meta: FrameInput,
        detections: DetectionOutput,
        depth: DepthOutput | None,
    ) -> NavigationOutput:
        import asyncio
        import cv2

        if self.server_url:
            result = await asyncio.to_thread(self._run_server, frame)
            action = _extract_action(result)
            return NavigationOutput(
                frame_id=meta.frame_id,
                timestamp=time.time(),
                decision=NavigationDecision(
                    action=action,
                    params=_params_for_action(action),
                    confidence=0.72 if action != "hover" else 0.67,
                    reasoning=f"Qwen3-VL server output: {result[-240:]}",
                    exploration_state="exploring",
                ),
            )

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
            image_path = handle.name
        try:
            cv2.imwrite(image_path, frame)
            result = await asyncio.to_thread(self._run_cli, image_path)
        finally:
            try:
                os.unlink(image_path)
            except FileNotFoundError:
                pass
        action = _extract_action(result)
        return NavigationOutput(
            frame_id=meta.frame_id,
            timestamp=time.time(),
            decision=NavigationDecision(
                action=action,
                params=_params_for_action(action),
                confidence=0.7 if action != "hover" else 0.65,
                reasoning=f"Qwen3-VL output: {result[-240:]}",
                exploration_state="exploring",
            ),
        )

    def _run_cli(self, image_path: str) -> str:
        prompt = (
            "You are controlling an indoor drone. Look at the image and return only compact JSON "
            "with keys action, confidence, reasoning. Allowed action values: hover, move_forward, "
            "rotate_left, rotate_right. If uncertain, choose hover."
        )
        completed = subprocess.run(
            [
                self.binary,
                "-m",
                self.model_path,
                "--mmproj",
                self.mmproj_path,
                "--image",
                image_path,
                "-p",
                prompt,
                "-n",
                "96",
                "--temp",
                "0",
                "--ctx-size",
                "4096",
            ],
            text=True,
            capture_output=True,
            timeout=float(os.environ.get("BREACHEYE_QWEN_TIMEOUT_S", "20")),
        )
        output = completed.stdout + "\n" + completed.stderr
        if completed.returncode != 0:
            raise ModelUnavailable(f"Qwen3-VL runtime failed: {output[-1000:]}")
        return output

    def _run_server(self, frame: Any) -> str:
        import cv2

        ok, encoded = cv2.imencode(".jpg", frame)
        if not ok:
            raise ModelUnavailable("failed to encode frame for Qwen server")
        image = base64.b64encode(encoded.tobytes()).decode("ascii")
        prompt = (
            "Return only compact JSON with keys action, confidence, reasoning. "
            "Allowed action values: hover, move_forward, rotate_left, rotate_right. "
            "If uncertain, choose hover. No markdown."
        )
        payload = {
            "model": "gpt-4-vision",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}"}},
                    ],
                }
            ],
            "temperature": 0,
            "max_tokens": int(os.environ.get("BREACHEYE_QWEN_MAX_TOKENS", "32")),
        }
        request = urllib.request.Request(
            self.server_url.rstrip("/") + "/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"content-type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=float(os.environ.get("BREACHEYE_QWEN_TIMEOUT_S", "20"))) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]


class SmolVLMNavigator(NavigationAdapter):
    name = "smolvlm2-500m"

    def __init__(self, model_path: str | None = None, device: str | None = None) -> None:
        self.model_path = model_path or os.environ.get("BREACHEYE_SMOLVLM_PATH")
        if not self.model_path:
            raise ModelUnavailable("BREACHEYE_SMOLVLM_PATH is not set")
        try:
            import torch
            from transformers import AutoModelForImageTextToText, AutoProcessor
        except ImportError as exc:
            raise ModelUnavailable("transformers and torch are required for SmolVLM") from exc
        self.torch = torch
        self.device = device or os.environ.get("BREACHEYE_SMOLVLM_DEVICE", "cpu")
        self.processor = AutoProcessor.from_pretrained(self.model_path, trust_remote_code=True)
        self.model = AutoModelForImageTextToText.from_pretrained(
            self.model_path,
            dtype=torch.float32,
            trust_remote_code=True,
            low_cpu_mem_usage=True,
        )
        self.model.to(self.device)
        self.model.eval()

    async def decide(
        self,
        frame: Any,
        meta: FrameInput,
        detections: DetectionOutput,
        depth: DepthOutput | None,
    ) -> NavigationOutput:
        from PIL import Image

        image = Image.fromarray(_bgr_to_rgb(frame))
        prompt = (
            "You are controlling an indoor drone. Return only compact JSON with keys "
            "action, confidence, reasoning. Allowed actions: hover, move_forward, "
            "rotate_left, rotate_right. If uncertain, choose hover."
        )
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        inputs = self.processor.apply_chat_template(
            messages,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
        )
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with self.torch.inference_mode():
            generated = self.model.generate(**inputs, do_sample=False, max_new_tokens=64)
        text = self.processor.batch_decode(generated, skip_special_tokens=True)[0]
        action = _extract_action(text)
        return NavigationOutput(
            frame_id=meta.frame_id,
            timestamp=time.time(),
            decision=NavigationDecision(
                action=action,
                params=_params_for_action(action),
                confidence=0.55 if action != "hover" else 0.5,
                reasoning=f"SmolVLM output: {text[-240:]}",
                exploration_state="exploring",
            ),
        )


def _extract_action(text: str) -> str:
    allowed = {"hover", "move_forward", "rotate_left", "rotate_right"}
    for action in allowed:
        if re.search(rf"\b{re.escape(action)}\b", text, flags=re.IGNORECASE):
            return action
    return "hover"


def _binary_available(binary: str) -> bool:
    from shutil import which

    return which(binary) is not None


def _params_for_action(action: str) -> dict[str, int]:
    if action == "move_forward":
        return {"distance_cm": 30, "speed_cm_s": 20}
    if action in {"rotate_left", "rotate_right"}:
        return {"degrees": 20}
    return {"duration_ms": 500}


def _bgr_to_rgb(frame: Any) -> Any:
    try:
        return frame[:, :, ::-1]
    except Exception:
        return frame
