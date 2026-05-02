import json
from pathlib import Path

from breacheye.rafa.readiness import check_rafa_readiness


def test_readiness_reports_stub_and_model_state(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("breacheye.rafa.readiness._ollama_models", lambda: ["qwen3.6:35b-a3b-q4_K_M"])
    monkeypatch.delenv("BREACHEYE_MOONDREAM_WEIGHTS", raising=False)
    monkeypatch.delenv("BREACHEYE_DEPTH_ANYTHING_WEIGHTS", raising=False)
    monkeypatch.delenv("BREACHEYE_QWEN_MODEL", raising=False)

    readiness = check_rafa_readiness(tmp_path)

    assert readiness.stub_ready is True
    assert readiness.models_ready is False
    assert "stub_ready" in json.loads(readiness.to_json())
    assert "no Qwen VL model" in readiness.to_text()


def test_readiness_accepts_existing_weight_paths(monkeypatch, tmp_path: Path) -> None:
    moondream = tmp_path / "moondream"
    depth = tmp_path / "depth"
    qwen = tmp_path / "qwen.gguf"
    moondream.mkdir()
    depth.mkdir()
    qwen.write_bytes(b"placeholder")
    monkeypatch.setenv("BREACHEYE_MOONDREAM_WEIGHTS", str(moondream))
    monkeypatch.setenv("BREACHEYE_DEPTH_ANYTHING_WEIGHTS", str(depth))
    monkeypatch.setenv("BREACHEYE_QWEN_MODEL", str(qwen))

    readiness = check_rafa_readiness(tmp_path)

    path_checks = {
        check.name: check.ready
        for check in readiness.model_checks
        if check.name
        in {"BREACHEYE_MOONDREAM_WEIGHTS", "BREACHEYE_DEPTH_ANYTHING_WEIGHTS", "qwen3_vl"}
    }
    assert path_checks == {
        "BREACHEYE_MOONDREAM_WEIGHTS": True,
        "BREACHEYE_DEPTH_ANYTHING_WEIGHTS": True,
        "qwen3_vl": True,
    }
