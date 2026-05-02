import numpy as np

from breacheye.rafa.codec import decode_frame
from integration.frame_publisher import frame_payload, synthetic_frames


def test_frame_payload_matches_frame_contract() -> None:
    frame = np.zeros((6, 8, 3), dtype=np.uint8)

    payload = frame_payload(12, frame, width=8, height=6)
    decoded = decode_frame(payload)

    assert decoded.frame_id == 12
    assert decoded.width == 8
    assert decoded.height == 6
    assert decoded.jpeg_bytes


def test_synthetic_frames_are_bgr_arrays() -> None:
    frame = next(synthetic_frames(width=32, height=24))

    assert frame.shape == (24, 32, 3)
    assert frame.dtype == np.uint8
