from breacheye.flight import (
    FlightLaunchConfig,
    _apply_local_model_defaults,
    _post_command_checked,
    _post_shutdown_land,
    _post_takeoff,
    build_process_specs,
)

import pytest


def test_tello_flight_defaults_to_harness_frame_source() -> None:
    specs = build_process_specs(FlightLaunchConfig(mode="tello", rafa_mode="models", run_id="run-1"))

    by_name = {spec.name: spec.argv for spec in specs}

    assert by_name["harness"][-6:] == ["--mode", "tello", "--host", "127.0.0.1", "--port", "8000"]
    assert "--mode" in by_name["rafa"]
    assert "models" in by_name["rafa"]
    assert "--harness-url" in by_name["frame_publisher"]
    assert "http://127.0.0.1:8000/frame/latest" in by_name["frame_publisher"]
    assert "http://127.0.0.1:8000/commands" in by_name["nav_interpreter"]
    assert "--run-id" in by_name["map_builder"]


def test_sim_flight_defaults_to_synthetic_frames() -> None:
    specs = build_process_specs(FlightLaunchConfig(mode="sim"))
    publisher = {spec.name: spec.argv for spec in specs}["frame_publisher"]

    assert "--harness-url" not in publisher
    assert "--tello" not in publisher


def test_model_flight_applies_local_model_defaults(monkeypatch, tmp_path) -> None:
    model = tmp_path / "models/qwen3-vl-2b/Qwen3-VL-2B-Instruct-Q4_K_M.gguf"
    mmproj = tmp_path / "models/qwen3-vl-2b/mmproj-F16.gguf"
    depth = tmp_path / "models/depth-anything-v2-small-hf"
    smol = tmp_path / "models/smolvlm2-500m"
    for path in [model, mmproj]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"model")
    depth.mkdir(parents=True)
    smol.mkdir(parents=True)

    monkeypatch.setattr("breacheye.flight._repo_root", lambda: tmp_path)
    monkeypatch.setattr("breacheye.flight._qwen_server_available", lambda: True)
    env: dict[str, str] = {}

    _apply_local_model_defaults(env, "models")

    assert env["BREACHEYE_QWEN_MODEL"] == str(model)
    assert env["BREACHEYE_QWEN_MMPROJ"] == str(mmproj)
    assert env["BREACHEYE_DEPTH_ANYTHING_PATH"] == str(depth)
    assert env["BREACHEYE_QWEN_SERVER_URL"] == "http://127.0.0.1:56262"


def test_shutdown_land_posts_hover_then_land(monkeypatch) -> None:
    calls = []

    class FakeResponse:
        status_code = 200

        def __init__(self, payload=None) -> None:
            self._payload = payload or {}
            self.text = str(self._payload)

        def json(self):
            return self._payload

    def fake_get(url, timeout):
        calls.append(("get", url, timeout))
        return FakeResponse({"telemetry": {"flying": True}})

    def fake_post(url, json, timeout):
        calls.append(("post", url, json["type"], timeout))
        return FakeResponse({"status": "executed"})

    monkeypatch.setattr("httpx.get", fake_get)
    monkeypatch.setattr("httpx.post", fake_post)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    _post_shutdown_land("http://harness")

    assert calls == [
        ("get", "http://harness/health", 1.5),
        ("post", "http://harness/commands", "hover", 8.0),
        ("post", "http://harness/commands", "land", 8.0),
    ]


def test_auto_takeoff_posts_bounded_climb_pulses_after_flying(monkeypatch) -> None:
    calls = []

    class FakeResponse:
        status_code = 200
        text = '{"status":"executed"}'

        def __init__(self, payload=None) -> None:
            self._payload = payload or {}

        def json(self):
            return self._payload

        def raise_for_status(self) -> None:
            return None

    def fake_get(url, timeout):
        calls.append(("get", url, timeout))
        return FakeResponse({"telemetry": {"flying": True}})

    def fake_post(url, json, timeout):
        calls.append(("post", url, json, timeout))
        return FakeResponse({"status": "executed"})

    monkeypatch.setattr("httpx.get", fake_get)
    monkeypatch.setattr("httpx.post", fake_post)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    _post_takeoff("http://harness", climb_cm=100)

    assert calls[0] == ("post", "http://harness/commands", {"type": "takeoff", "issued_by": "flight_launcher"}, 5.0)
    assert calls[1] == ("get", "http://harness/health", 1.0)
    climb_pulses = calls[2:]
    assert len(climb_pulses) == 4
    assert all(call[0] == "post" for call in climb_pulses)
    assert all(call[2]["type"] == "rc_control" for call in climb_pulses)
    assert all(call[2]["payload"]["up_down"] == 30 for call in climb_pulses)
    assert [call[2]["payload"]["duration_ms"] for call in climb_pulses] == [1000, 1000, 1000, 333]


def test_post_command_checked_raises_on_failed_body(monkeypatch) -> None:
    class FakeResponse:
        text = '{"status":"failed","reason":"no lift"}'

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"status": "failed", "reason": "no lift"}

    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(RuntimeError, match="no lift"):
        _post_command_checked("http://harness", {"type": "takeoff"}, label="takeoff")
