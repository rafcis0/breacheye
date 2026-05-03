from breacheye.rafa.adapters import HoverNavigator
from breacheye.rafa.orchestrator import RafaPipeline, RafaPipelineConfig


def test_models_mode_without_vlm_uses_hover_navigator(monkeypatch, tmp_path) -> None:
    for key in [
        "BREACHEYE_QWEN_MODEL",
        "BREACHEYE_QWEN_MMPROJ",
        "BREACHEYE_QWEN_SERVER_URL",
        "BREACHEYE_SMOLVLM_PATH",
    ]:
        monkeypatch.delenv(key, raising=False)

    pipeline = RafaPipeline(RafaPipelineConfig(mode="models", log_dir=str(tmp_path), run_id="fallback-test"))
    pipeline.configure_adapters()

    assert isinstance(pipeline.navigator, HoverNavigator)
    assert pipeline.model_status["qwen3_vl"].active == "hover-navigator"
