from breacheye.flight import (
    FlightLaunchConfig,
    _apply_local_model_defaults,
    _apply_live_safety_defaults,
    _command_timeout_s,
    _harness_health_summary,
    _post_command_checked,
    _post_shutdown_land,
    _post_shutdown_stop_video,
    _shutdown_emergency_reasons,
    _post_takeoff,
    _rafa_log_has_navigation,
    _takeoff_stability_gate,
    _wait_for_accepts_nav,
    _wait_for_first_frame,
    _wait_for_rafa_navigation,
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


def test_tello_auto_takeoff_starts_background_before_deferred_harness() -> None:
    specs = build_process_specs(
        FlightLaunchConfig(mode="tello", rafa_mode="models", run_id="run-1", auto_takeoff=True)
    )

    assert [spec.name for spec in specs] == [
        "rafa",
        "frame_publisher",
        "nav_interpreter",
        "map_builder",
        "harness",
    ]
    assert "--defer-video" in specs[-1].argv
    assert next(spec for spec in specs if spec.name == "nav_interpreter").post_takeoff is True


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


def test_live_safety_defaults_enable_stabilizer_log_for_auto_takeoff() -> None:
    env: dict[str, str] = {}

    _apply_live_safety_defaults(env, mode="tello", auto_takeoff=True)

    assert env["BREACHEYE_STABILIZER_MODE"] == "log"


def test_live_safety_defaults_preserve_explicit_stabilizer_mode() -> None:
    env = {"BREACHEYE_STABILIZER_MODE": "assist"}

    _apply_live_safety_defaults(env, mode="live", auto_takeoff=True)

    assert env["BREACHEYE_STABILIZER_MODE"] == "assist"


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
        ("post", "http://harness/commands", "land", 15.0),
    ]


def test_shutdown_land_escalates_to_emergency_when_land_fails_and_drone_is_stuck(monkeypatch) -> None:
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
        return FakeResponse(
            {
                "telemetry": {
                    "flying": True,
                    "height_cm": -20,
                    "raw": {"pitch": -46, "roll": -33, "tof": 31},
                },
                "video": {"running": True, "latest_sample": {"timestamp": 100.0}},
            }
        )

    def fake_post(url, json, timeout):
        calls.append(("post", url, json["type"], timeout))
        if json["type"] == "land":
            return FakeResponse({"status": "failed", "reason": "timeout"})
        return FakeResponse({"status": "executed"})

    monkeypatch.setattr("httpx.get", fake_get)
    monkeypatch.setattr("httpx.post", fake_post)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    monkeypatch.setattr("time.time", lambda: 120.0)

    _post_shutdown_land("http://harness")

    assert calls == [
        ("get", "http://harness/health", 1.5),
        ("post", "http://harness/commands", "hover", 8.0),
        ("post", "http://harness/commands", "land", 15.0),
        ("get", "http://harness/health", 1.5),
        ("post", "http://harness/commands", "emergency", 5.0),
    ]


def test_shutdown_emergency_reasons_include_attitude_ground_and_stale_video() -> None:
    reasons = _shutdown_emergency_reasons(
        {
            "telemetry": {
                "flying": True,
                "height_cm": -20,
                "raw": {"pitch": -46, "roll": -33, "tof": 31},
            },
            "video": {"running": True, "latest_sample": {"timestamp": 100.0}},
        },
        now=120.0,
    )

    assert "pitch=-46" in reasons
    assert "height_cm=-20 tof=31" in reasons
    assert "stale_video_sample=20.0s" in reasons


def test_shutdown_stop_video_posts_video_stop(monkeypatch) -> None:
    calls = []

    class FakeResponse:
        text = '{"stopped":true}'

    def fake_post(url, timeout):
        calls.append((url, timeout))
        return FakeResponse()

    monkeypatch.setattr("httpx.post", fake_post)

    _post_shutdown_stop_video("http://harness")

    assert calls == [("http://harness/video/stop", 5.0)]


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

    def fake_post(url, json, timeout):
        calls.append(("post", url, json, timeout))
        return FakeResponse({"status": "executed"})

    flying_checks = {"count": 0}

    def fake_wait_for_flying(_base_url, timeout_s=5.0):
        calls.append(("wait_for_flying", _base_url, timeout_s))
        flying_checks["count"] += 1
        return flying_checks["count"] > 1

    monkeypatch.setattr("httpx.post", fake_post)
    monkeypatch.setattr("breacheye.flight._wait_for_flying", fake_wait_for_flying)
    monkeypatch.setattr("breacheye.flight._takeoff_stability_gate", lambda _base_url: None)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    _post_takeoff("http://harness", climb_cm=100)

    assert calls[0] == ("wait_for_flying", "http://harness", 0.1)
    assert calls[1] == ("post", "http://harness/commands", {"type": "takeoff", "issued_by": "flight_launcher"}, 30.0)
    assert calls[2] == ("wait_for_flying", "http://harness", 5.0)
    climb_pulses = calls[3:]
    assert len(climb_pulses) == 5
    assert all(call[0] == "post" for call in climb_pulses)
    assert all(call[2]["type"] == "rc_control" for call in climb_pulses)
    assert all(call[2]["payload"]["up_down"] == 20 for call in climb_pulses)
    assert [call[2]["payload"]["duration_ms"] for call in climb_pulses] == [1000, 1000, 1000, 1000, 1000]


def test_auto_takeoff_starts_video_after_settle_and_climb(monkeypatch) -> None:
    calls = []

    class FakeResponse:
        text = '{"status":"executed"}'

        def json(self):
            return {"status": "executed"}

        def raise_for_status(self) -> None:
            return None

    def fake_post(url, json, timeout):
        calls.append(("post", url, json, timeout))
        return FakeResponse()

    flying_checks = {"count": 0}

    def fake_wait_for_flying(_base_url, timeout_s=5.0):
        calls.append(("wait_for_flying", _base_url, timeout_s))
        flying_checks["count"] += 1
        return flying_checks["count"] > 1

    monkeypatch.setattr("httpx.post", fake_post)
    monkeypatch.setattr("breacheye.flight._wait_for_flying", fake_wait_for_flying)
    monkeypatch.setattr("breacheye.flight._takeoff_stability_gate", lambda _base_url: None)
    monkeypatch.setattr("time.sleep", lambda seconds: calls.append(("sleep", seconds)))

    _post_takeoff("http://harness", climb_cm=20, after_takeoff=lambda: calls.append(("video_start",)))

    assert ("sleep", 3.0) in calls
    assert calls[-1] == ("video_start",)


def test_takeoff_stability_gate_accepts_stable_samples(monkeypatch) -> None:
    calls = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "telemetry": {"flying": True},
                "stabilizer": {
                    "mode": "log",
                    "running": True,
                    "last_estimate": {
                        "timestamp": 100.0,
                        "median_dx_px": 0.5,
                        "median_dy_px": -0.2,
                        "median_radial_px": 0.1,
                    },
                },
            }

    def fake_get(url, timeout):
        calls.append((url, timeout))
        return FakeResponse()

    monkeypatch.setattr("httpx.get", fake_get)
    monkeypatch.setattr("time.time", lambda: 100.2)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    _takeoff_stability_gate("http://harness", prefix="[test]")

    assert len(calls) == 2


def test_takeoff_stability_gate_lands_on_repeated_drift(monkeypatch) -> None:
    calls = []

    class FakeGetResponse:
        status_code = 200

        def json(self):
            return {
                "telemetry": {"flying": True},
                "stabilizer": {
                    "mode": "log",
                    "running": True,
                    "last_estimate": {
                        "timestamp": 100.0,
                        "median_dx_px": 5.2,
                        "median_dy_px": 0.0,
                        "median_radial_px": 0.0,
                    },
                },
            }

    class FakePostResponse:
        text = '{"status":"executed"}'

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"status": "executed"}

    def fake_get(url, timeout):
        calls.append(("get", url, timeout))
        return FakeGetResponse()

    def fake_post(url, json, timeout):
        calls.append(("post", url, json["type"], timeout))
        return FakePostResponse()

    monkeypatch.setattr("httpx.get", fake_get)
    monkeypatch.setattr("httpx.post", fake_post)
    monkeypatch.setattr("time.time", lambda: 100.2)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="takeoff stability gate failed"):
        _takeoff_stability_gate("http://harness", prefix="[test]")

    assert calls[-2:] == [
        ("post", "http://harness/commands", "hover", 5.0),
        ("post", "http://harness/commands", "land", 30.0),
    ]


def test_takeoff_stability_gate_skips_when_no_fresh_sample(monkeypatch) -> None:
    calls = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "telemetry": {"flying": True},
                "stabilizer": {
                    "mode": "log",
                    "running": True,
                    "last_skip_reason": "height_too_low:30",
                    "last_estimate": {},
                },
            }

    def fake_get(url, timeout):
        calls.append((url, timeout))
        return FakeResponse()

    times = iter([0.0, 0.0, 0.2, 0.4, 0.6])
    monkeypatch.setenv("BREACHEYE_TAKEOFF_STABILITY_TIMEOUT_S", "0.5")
    monkeypatch.setenv("BREACHEYE_TAKEOFF_STABILITY_SAMPLE_S", "0.1")
    monkeypatch.setattr("httpx.get", fake_get)
    monkeypatch.setattr("time.monotonic", lambda: next(times))
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    _takeoff_stability_gate("http://harness", prefix="[test]")

    assert calls


def test_wait_for_first_frame_requires_full_size(monkeypatch) -> None:
    import cv2
    import numpy as np

    def jpeg(width: int, height: int) -> bytes:
        image = np.zeros((height, width, 3), dtype=np.uint8)
        ok, encoded = cv2.imencode(".jpg", image)
        assert ok
        return encoded.tobytes()

    class FakeResponse:
        status_code = 200

        def __init__(self, content: bytes) -> None:
            self.content = content

    responses = [FakeResponse(jpeg(400, 300)), FakeResponse(jpeg(960, 720))]
    calls = []

    def fake_get(url, timeout):
        calls.append((url, timeout))
        return responses.pop(0)

    monkeypatch.setattr("httpx.get", fake_get)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    _wait_for_first_frame("http://harness", timeout_s=1.0)

    assert len(calls) == 2


def test_post_command_checked_raises_on_failed_body(monkeypatch) -> None:
    class FakeResponse:
        text = '{"status":"failed","reason":"no lift"}'

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"status": "failed", "reason": "no lift"}

    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr("breacheye.flight._harness_health_summary", lambda _base_url: "battery=42")

    with pytest.raises(RuntimeError, match="no lift; harness health: battery=42"):
        _post_command_checked("http://harness", {"type": "takeoff"}, label="takeoff")


def test_launch_commands_get_longer_http_timeout() -> None:
    assert _command_timeout_s({"type": "takeoff"}) == 30.0
    assert _command_timeout_s({"type": "land"}) == 30.0
    assert _command_timeout_s({"type": "rc_control"}) == 5.0


def test_harness_health_summary_includes_takeoff_diagnostics(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "telemetry": {
                    "connected": True,
                    "flying": False,
                    "battery": 71,
                    "height_cm": 0,
                    "flight_time_s": 0,
                }
            }

    monkeypatch.setattr("httpx.get", lambda *args, **kwargs: FakeResponse())

    assert _harness_health_summary("http://harness") == (
        "connected=True, flying=False, battery=71, height_cm=0, flight_time_s=0, "
        "tof=None, templ=None, temph=None, pitch=None, roll=None"
    )


def test_rafa_log_has_navigation(tmp_path) -> None:
    path = tmp_path / "run-rafa.jsonl"
    path.write_text('{"event":"publish","channel":"navigation"}\n', encoding="utf-8")

    assert _rafa_log_has_navigation(path) is True


def test_wait_for_rafa_navigation_refuses_timeout(tmp_path, monkeypatch) -> None:
    current = {"value": 0.0}

    def fake_monotonic():
        current["value"] += 1.0
        return current["value"]

    monkeypatch.setattr("time.monotonic", fake_monotonic)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="refusing auto-takeoff"):
        _wait_for_rafa_navigation(str(tmp_path), "missing", "[test]", timeout_s=1.0)


def test_wait_for_accepts_nav_requires_enabled_health(monkeypatch) -> None:
    calls = []

    class FakeResponse:
        status_code = 200

        def __init__(self, accepts_nav: bool) -> None:
            self._accepts_nav = accepts_nav

        def json(self):
            return {
                "accepts_nav": self._accepts_nav,
                "telemetry": {"connected": True, "flying": True, "battery": 80},
            }

    def fake_get(url, timeout):
        calls.append((url, timeout))
        return FakeResponse(accepts_nav=len(calls) > 1)

    monkeypatch.setattr("httpx.get", fake_get)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    _wait_for_accepts_nav("http://harness", prefix="[test]", timeout_s=2.0)

    assert len(calls) == 2


def test_wait_for_accepts_nav_times_out_when_state_machine_stays_closed(monkeypatch) -> None:
    current = {"value": 0.0}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "accepts_nav": False,
                "telemetry": {"connected": True, "flying": True, "battery": 80},
            }

    def fake_monotonic():
        current["value"] += 1.0
        return current["value"]

    monkeypatch.setattr("httpx.get", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr("time.monotonic", fake_monotonic)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="autonomous nav did not become enabled"):
        _wait_for_accepts_nav("http://harness", prefix="[test]", timeout_s=1.0)
