from breacheye.rafa.adapters import SafeRuleNavigator
from breacheye.rafa.orchestrator import RafaPipeline, RafaPipelineConfig


def test_models_mode_without_vlm_uses_safe_rule_navigator(monkeypatch, tmp_path) -> None:
    for key in [
        "BREACHEYE_QWEN_MODEL",
        "BREACHEYE_QWEN_MMPROJ",
        "BREACHEYE_QWEN_SERVER_URL",
        "BREACHEYE_SMOLVLM_PATH",
    ]:
        monkeypatch.delenv(key, raising=False)

    pipeline = RafaPipeline(RafaPipelineConfig(mode="models", log_dir=str(tmp_path), run_id="fallback-test"))
    pipeline.configure_adapters()

    assert isinstance(pipeline.navigator, SafeRuleNavigator)
    assert pipeline.model_status["qwen3_vl"].active == "safe-rule-navigator"
