from fastapi.testclient import TestClient

from breacheye.service import create_app


def test_health_endpoint_in_sim_mode() -> None:
    with TestClient(create_app(mode="sim")) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "sim"
    assert body["telemetry"]["connected"] is True


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
