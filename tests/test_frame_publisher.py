import numpy as np

from breacheye.rafa.codec import decode_frame
from breacheye.video import encode_jpeg
from integration.frame_publisher import frame_payload, harness_frames, synthetic_frames


def test_frame_payload_matches_frame_contract() -> None:
    frame = np.zeros((6, 8, 3), dtype=np.uint8)
    jpeg_bytes = encode_jpeg(frame)

    payload = frame_payload(12, jpeg_bytes, width=8, height=6)
    decoded = decode_frame(payload)

    assert decoded.frame_id == 12
    assert decoded.width == 8
    assert decoded.height == 6
    assert decoded.jpeg_bytes == jpeg_bytes


def test_synthetic_frames_are_bgr_arrays() -> None:
    frame = next(synthetic_frames(width=32, height=24))

    assert frame.shape == (24, 32, 3)
    assert frame.dtype == np.uint8


def test_harness_frames_decodes_latest_frame(monkeypatch) -> None:
    frame = np.zeros((6, 8, 3), dtype=np.uint8)
    jpeg = encode_jpeg(frame)

    class FakeResponse:
        status_code = 200
        content = jpeg

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def get(self, url):
            assert url == "http://harness/frame/latest"
            return FakeResponse()

    import httpx

    monkeypatch.setattr(httpx, "Client", FakeClient)

    decoded = next(harness_frames("http://harness/frame/latest"))

    assert decoded.shape == (6, 8, 3)
    assert decoded.dtype == np.uint8
