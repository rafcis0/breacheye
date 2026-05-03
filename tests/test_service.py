from fastapi.testclient import TestClient

from breacheye.service import create_app


def test_health_endpoint_in_sim_mode() -> None:
    with TestClient(create_app(mode="sim")) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "sim"
    assert body["telemetry"]["connected"] is True
    assert body["video"]["running"] is False


def test_video_start_stop_endpoint_in_sim_mode() -> None:
    with TestClient(create_app(mode="sim")) as client:
        start = client.post("/video/start")
        stop = client.post("/video/stop")

    assert start.status_code == 200
    assert start.json() == {"running": False}
    assert stop.status_code == 200
    assert stop.json() == {"stopped": False, "running": False}


def test_command_endpoint_executes_takeoff_in_sim_mode() -> None:
    with TestClient(create_app(mode="sim")) as client:
        response = client.post("/commands", json={"type": "takeoff", "issued_by": "test"})

    assert response.status_code == 200
    assert response.json()["status"] == "executed"


def test_command_endpoint_executes_land_in_sim_mode() -> None:
    with TestClient(create_app(mode="sim")) as client:
        client.post("/commands", json={"type": "takeoff", "issued_by": "test"})
        response = client.post("/commands", json={"type": "land", "issued_by": "test"})

    assert response.status_code == 200
    assert response.json()["status"] == "executed"


def test_latest_frame_returns_404_without_video() -> None:
    with TestClient(create_app(mode="sim")) as client:
        response = client.get("/frame/latest")

    assert response.status_code == 404


def test_latest_point_cloud_returns_404_without_artifact(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("BREACHEYE_LOG_DIR", str(tmp_path))
    monkeypatch.delenv("BREACHEYE_RUN_ID", raising=False)

    with TestClient(create_app(mode="sim")) as client:
        response = client.get("/map/point-cloud/latest")

    assert response.status_code == 404


def test_latest_point_cloud_returns_run_artifact(monkeypatch, tmp_path) -> None:
    run_id = "map-test"
    out = tmp_path / run_id / "map"
    out.mkdir(parents=True)
    (out / "point-cloud.json").write_text('{"points":[]}', encoding="utf-8")
    monkeypatch.setenv("BREACHEYE_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("BREACHEYE_RUN_ID", run_id)

    with TestClient(create_app(mode="sim")) as client:
        response = client.get("/map/point-cloud/latest")

    assert response.status_code == 200
    assert response.json() == {"points": []}


def test_latest_depth_map_returns_run_artifact(monkeypatch, tmp_path) -> None:
    run_id = "depth-test"
    out = tmp_path / run_id / "rafa" / "depth"
    out.mkdir(parents=True)
    png_bytes = b"\x89PNG\r\n\x1a\nfake"
    (out / "frame-00000001.png").write_bytes(png_bytes)
    monkeypatch.setenv("BREACHEYE_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("BREACHEYE_RUN_ID", run_id)

    with TestClient(create_app(mode="sim")) as client:
        response = client.get("/map/depth/latest")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == png_bytes
