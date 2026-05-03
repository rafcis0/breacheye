from __future__ import annotations

from breacheye.flight import build_demo_specs, _resolve_demo_mode


def test_mock_mode_specs():
    specs = build_demo_specs("mock")
    names = [s.name for s in specs]
    assert "harness" in names
    assert "frame_publisher" in names
    assert "mock_detections" in names
    assert "mock_navigation" in names
    assert "mock_telemetry" in names
    assert "nav_interpreter" in names
    # No rafa or playback in mock mode
    assert "rafa" not in names
    assert "playback" not in names


def test_recorded_mode_specs():
    specs = build_demo_specs("recorded")
    names = [s.name for s in specs]
    assert "harness" in names
    assert "playback" in names
    assert "mock_navigation" in names
    assert "mock_telemetry" in names
    assert "nav_interpreter" in names
    # No frame_publisher or rafa or mock_detections
    assert "frame_publisher" not in names
    assert "rafa" not in names
    assert "mock_detections" not in names


def test_live_mode_specs():
    specs = build_demo_specs("live")
    names = [s.name for s in specs]
    assert "harness" in names
    assert "rafa" in names
    assert "frame_publisher" in names
    assert "nav_interpreter" in names
    # No mocks in live
    assert "playback" not in names
    assert "mock_detections" not in names


def test_live_mode_reads_frames_from_harness():
    specs = build_demo_specs("live")
    publisher = [s for s in specs if s.name == "frame_publisher"][0]

    assert "--harness-url" in publisher.argv
    assert "--tello" not in publisher.argv
    assert "http://127.0.0.1:8000/frame/latest" in publisher.argv


def test_harness_mode_sim_for_mock():
    specs = build_demo_specs("mock")
    harness = [s for s in specs if s.name == "harness"][0]
    assert "--mode" in harness.argv
    idx = harness.argv.index("--mode")
    assert harness.argv[idx + 1] == "sim"


def test_harness_mode_tello_for_live():
    specs = build_demo_specs("live")
    harness = [s for s in specs if s.name == "harness"][0]
    idx = harness.argv.index("--mode")
    assert harness.argv[idx + 1] == "tello"


def test_resolve_recorded_degrades_to_mock_if_no_video():
    resolved = _resolve_demo_mode("recorded", "/nonexistent/video.mp4")
    assert resolved == "mock"


def test_nav_interpreter_in_all_modes():
    for mode in ("live", "recorded", "mock"):
        specs = build_demo_specs(mode)
        names = [s.name for s in specs]
        assert "nav_interpreter" in names, f"nav_interpreter missing in {mode} mode"
