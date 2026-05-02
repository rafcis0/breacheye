import numpy as np
import pytest

from breacheye.rafa.jpeg import decode_jpeg_bgr
from breacheye.video import encode_jpeg


def test_decode_valid_jpeg_bytes() -> None:
    frame = np.zeros((4, 6, 3), dtype=np.uint8)

    decoded = decode_jpeg_bgr(encode_jpeg(frame))

    assert decoded.shape == (4, 6, 3)


def test_decode_corrupt_jpeg_bytes_raises() -> None:
    with pytest.raises(ValueError):
        decode_jpeg_bgr(b"not-a-jpeg")
