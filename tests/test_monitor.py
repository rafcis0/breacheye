import os
import time

from breacheye.monitor import resolve_run_id, summarize_event


def test_resolve_run_id_picks_latest_component_log(tmp_path) -> None:
    old = tmp_path / "run-old-rafa.jsonl"
    new = tmp_path / "run-new-nav_interpreter.jsonl"
    old.write_text("{}\n", encoding="utf-8")
    new.write_text("{}\n", encoding="utf-8")
    now = time.time()
    os.utime(old, (now - 10, now - 10))
    os.utime(new, (now, now))

    assert resolve_run_id(tmp_path, "latest") == "run-new"


def test_summarize_navigation_and_command_events() -> None:
    nav_line = summarize_event(
        {
            "component": "nav_interpreter",
            "event": "navigation_received",
            "frame_id": 12,
            "action": "move_forward",
            "confidence": 0.72,
            "reasoning": "clear path",
        }
    )
    command_line = summarize_event(
        {
            "component": "nav_interpreter",
            "event": "command_posted",
            "command_type": "rc_control",
            "response_status": "executed",
            "command_payload": {"forward_back": 20},
        }
    )

    assert "move_forward" in nav_line
    assert "rc_control" in command_line
    assert "executed" in command_line


def test_summarize_map_update_event() -> None:
    line = summarize_event(
        {
            "component": "map_builder",
            "event": "map_updated",
            "stats": {"points": 128, "frames_used": 4},
            "source": "depth_anything_relative_live",
        }
    )

    assert line == "[map] points=128 frames=4 source=depth_anything_relative_live"
