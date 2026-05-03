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
            relative = _depth_anything_to_relative_far(depth, near=near, far=far)
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

        depth_hint = _depth_prompt_hint(depth)
        if self.server_url:
            result = await asyncio.to_thread(self._run_server, frame, depth_hint)
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
            result = await asyncio.to_thread(self._run_cli, image_path, depth_hint)
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

    def _run_cli(self, image_path: str, depth_hint: str) -> str:
        prompt = (
            "You are controlling an indoor drone. Look at the image and return only compact JSON "
            "with keys action, confidence, reasoning. Allowed action values: hover, move_forward, "
            "rotate_left, rotate_right. Choose move_forward only when the center path is clear. "
            "Choose rotate_left or rotate_right to scan when the path is unclear or partially blocked. "
            "Use hover only for immediate obstacles, people too close, invalid image, or unsafe flight. "
            f"{depth_hint}"
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

    def _run_server(self, frame: Any, depth_hint: str) -> str:
        import cv2

        ok, encoded = cv2.imencode(".jpg", frame)
        if not ok:
            raise ModelUnavailable("failed to encode frame for Qwen server")
        image = base64.b64encode(encoded.tobytes()).decode("ascii")
        prompt = (
            "Return only compact JSON with keys action, confidence, reasoning. "
            "Allowed action values: hover, move_forward, rotate_left, rotate_right. "
            "Choose move_forward only when the center path is clear. Choose rotate_left or "
            "rotate_right to scan when the path is unclear or partially blocked. Use hover "
            "only for immediate obstacles, people too close, invalid image, or unsafe flight. "
            f"{depth_hint} No markdown."
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
            "rotate_left, rotate_right. Choose move_forward only when the center path is clear. "
            "Choose rotate_left or rotate_right to scan when the path is unclear or partially blocked. "
            "Use hover only for immediate obstacles, people too close, invalid image, or unsafe flight."
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
    try:
        match = re.search(r"\{.*?\}", text, flags=re.DOTALL)
        if match:
            parsed = json.loads(match.group(0))
            action = str(parsed.get("action", "")).lower()
            if action in allowed:
                return action
    except Exception:
        pass
    for action in ("move_forward", "rotate_left", "rotate_right", "hover"):
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


def _depth_prompt_hint(depth: DepthOutput | None) -> str:
    if depth is None:
        return "No depth map is available; be conservative."
    try:
        import numpy as np

        values = np.frombuffer(depth.depth_bytes, dtype=np.float32).reshape(depth.shape)
        clearance = _forward_clearance_score(values)
        if clearance is None:
            return "Depth forward corridor has no finite values; be conservative."
    except Exception:
        return "Depth map could not be summarized; be conservative."
    threshold = _env_float("BREACHEYE_NAV_MIN_FORWARD_CLEARANCE_M", 0.45, minimum=0.0, maximum=10.0)
    status = "blocked or marginal" if clearance <= threshold else "clearer"
    return (
        "Depth Anything relative depth hint: forward-corridor score is "
        f"{clearance:.3f}; forward-clear threshold is {threshold:.3f}; "
        f"corridor is {status}. Lower means closer, higher means farther. "
        "If the corridor is blocked or marginal, choose rotate_right instead of move_forward."
    )


def _env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _depth_anything_to_relative_far(depth: Any, *, near: float, far: float) -> Any:
    import numpy as np

    # Depth Anything V2's raw prediction behaves as inverse relative depth in
    # practice: larger values correspond to closer surfaces. The wire contract
    # is `relative_0_near_1_far`, so invert the normalized model output here.
    denom = max(far - near, 1e-6)
    inverse_relative = np.clip((depth - near) / denom, 0.0, 1.0)
    return (1.0 - inverse_relative).astype(np.float32)


def _forward_clearance_score(values: Any) -> float | None:
    import numpy as np

    height, width = values.shape
    center_band = values[height // 3 : (height * 2) // 3, width // 3 : (width * 2) // 3]
    lower_forward = values[
        int(height * 0.45) : int(height * 0.9),
        int(width * 0.25) : int(width * 0.75),
    ]
    scores = []
    center_finite = center_band[np.isfinite(center_band)]
    if center_finite.size:
        scores.append(float(np.nanpercentile(center_finite, 50)))
    lower_finite = lower_forward[np.isfinite(lower_forward)]
    if lower_finite.size:
        scores.append(float(np.nanpercentile(lower_finite, 20)))
    if not scores:
        return None
    return min(scores)
