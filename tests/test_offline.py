import json
import tarfile

from breacheye.offline import create_bundle, write_preflight
from breacheye.runlog import RunLogger


def test_offline_preflight_writes_metadata_and_log(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BREACHEYE_QWEN_MODEL", str(tmp_path / "qwen.gguf"))
    (tmp_path / "qwen.gguf").write_bytes(b"placeholder")

    metadata_path = write_preflight(log_dir=tmp_path, run_id="offline-test")

    assert metadata_path == tmp_path / "offline-test" / "run-metadata.json"
    data = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert data["run_id"] == "offline-test"
    assert data["env_paths"]["BREACHEYE_QWEN_MODEL"]["exists"] is True
    assert data["ports"]["frame_input"]["port"] == 5555
    assert (tmp_path / "offline-test-offline.jsonl").exists()


def test_offline_bundle_includes_jsonl_metadata_and_artifacts(tmp_path) -> None:
    logger = RunLogger("rafa", log_dir=tmp_path, run_id="bundle-test")
    logger.event("frame_received", frame_id=1)
    logger.save_bytes("frames", "frame-00000001.jpg", b"jpg")
    write_preflight(log_dir=tmp_path, run_id="bundle-test")

    bundle_path = create_bundle(log_dir=tmp_path, run_id="bundle-test")

    assert bundle_path.exists()
    with tarfile.open(bundle_path, "r:gz") as archive:
        names = set(archive.getnames())
    assert "bundle-test-rafa.jsonl" in names
    assert "bundle-test/run-metadata.json" in names
    assert "bundle-test/rafa/frames/frame-00000001.jpg" in names
