from breacheye.video import FrameStore


def test_frame_store_keeps_full_frame_and_samples_by_interval() -> None:
    store = FrameStore(sample_fps=1000)
    first = store.update_jpeg(b"one", width=2, height=1)
    second = store.update_jpeg(b"two", width=2, height=1)

    assert store.latest_full_jpeg() == b"two"
    assert first is not None
    assert first.width == 2
    assert first.height == 1
    assert second is None
    assert store.latest_sampled_jpeg() == b"one"
