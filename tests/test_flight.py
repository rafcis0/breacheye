from breacheye.flight import FlightLaunchConfig, build_process_specs


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
