import numpy as np

from breacheye.rafa.codec import decode_frame
from breacheye.video import encode_jpeg
from integration.frame_publisher import frame_payload, harness_frame_skip_reason, harness_frames, synthetic_frames


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

    decoded = next(
        harness_frames("http://harness/frame/latest", min_width=0, min_height=0, min_mean_luma=0, min_luma_stddev=0)
    )

    assert decoded.shape == (6, 8, 3)
    assert decoded.dtype == np.uint8


def test_harness_frames_waits_for_harness_connection(monkeypatch):
    frame = np.zeros((6, 8, 3), dtype=np.uint8)
    jpeg = encode_jpeg(frame)

    class FakeResponse:
        status_code = 200
        content = jpeg

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        calls = 0

        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def get(self, _url):
            import httpx

            FakeClient.calls += 1
            if FakeClient.calls == 1:
                raise httpx.ConnectError("not ready")
            return FakeResponse()

    import httpx

    monkeypatch.setattr(httpx, "Client", FakeClient)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    decoded = next(
        harness_frames("http://harness/frame/latest", min_width=0, min_height=0, min_mean_luma=0, min_luma_stddev=0)
    )

    assert decoded.shape == (6, 8, 3)
    assert FakeClient.calls == 2


def test_harness_frame_skip_reason_rejects_small_warmup_frame() -> None:
    frame = np.full((300, 400, 3), 128, dtype=np.uint8)

    assert harness_frame_skip_reason(frame) == "too_small"


def test_harness_frame_skip_reason_rejects_blank_frame() -> None:
    frame = np.zeros((720, 960, 3), dtype=np.uint8)

    assert harness_frame_skip_reason(frame) == "too_dark"


def test_harness_frame_skip_reason_accepts_real_sized_visible_frame() -> None:
    frame = np.full((720, 960, 3), 30, dtype=np.uint8)
    frame[:, 480:] = 180

    assert harness_frame_skip_reason(frame) is None
