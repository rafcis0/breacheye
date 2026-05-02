from __future__ import annotations

from typing import Any


def decode_jpeg_bgr(jpeg_bytes: bytes) -> Any:
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("opencv-python and numpy are required to decode JPEG frames") from exc

    buffer = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    frame = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("failed to decode JPEG frame")
    return frame
