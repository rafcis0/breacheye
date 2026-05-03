from breacheye.flight import FlightLaunchConfig, _apply_local_model_defaults, build_process_specs


def test_tello_flight_defaults_to_harness_frame_source() -> None:
    specs = build_process_specs(FlightLaunchConfig(mode="tello", rafa_mode="models", run_id="run-1"))

    by_name = {spec.name: spec.argv for spec in specs}

    assert by_name["harness"][-6:] == ["--mode", "tello", "--host", "127.0.0.1", "--port", "8000"]
    assert "--mode" in by_name["rafa"]
    assert "models" in by_name["rafa"]
    assert "--harness-url" in by_name["frame_publisher"]
    assert "http://127.0.0.1:8000/frame/latest" in by_name["frame_publisher"]
    assert "http://127.0.0.1:8000/commands" in by_name["nav_interpreter"]


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
