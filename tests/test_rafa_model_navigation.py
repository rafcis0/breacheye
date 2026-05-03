from breacheye.rafa.models import _extract_action


def test_extract_action_prefers_json_action_over_prompt_echo() -> None:
    text = 'Allowed: move_forward, rotate_left, hover. {"action":"rotate_right","confidence":0.8}'

    assert _extract_action(text) == "rotate_right"


def test_extract_action_fallback_prefers_motion_before_hover() -> None:
    assert _extract_action("I would rotate_left, otherwise hover.") == "rotate_left"
