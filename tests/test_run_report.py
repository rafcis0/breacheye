import json

from ai.run_report import build_report


def test_run_report_builds_html_with_assets(tmp_path) -> None:
    run_id = "report-test"
    log_dir = tmp_path / "logs"
    run_dir = log_dir / run_id
    (run_dir / "rafa" / "frames").mkdir(parents=True)
    (run_dir / "rafa" / "depth").mkdir(parents=True)
    (run_dir / "map").mkdir(parents=True)
    (run_dir / "rafa" / "frames" / "frame-00000001.jpg").write_bytes(b"jpg")
    (run_dir / "rafa" / "depth" / "frame-00000001.png").write_bytes(b"png")
    (run_dir / "map" / "relative-depth-topdown.png").write_bytes(b"png")
    (run_dir / "map" / "relative-depth-summary.json").write_text('{"points": 10}\n', encoding="utf-8")
    (run_dir / "run-metadata.json").write_text('{"env": {"BREACHEYE_RUN_ID": "report-test"}}\n', encoding="utf-8")
    (log_dir / f"{run_id}-frame_publisher.jsonl").write_text(
        json.dumps({"event": "frame_published", "frame_id": 1}) + "\n",
        encoding="utf-8",
    )
    (log_dir / f"{run_id}-rafa.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"event": "frame_received", "frame_id": 1}),
                json.dumps(
                    {
                        "component": "rafa",
                        "event": "navigation_decision_built",
                        "frame_id": 1,
                        "action": "hover",
                        "confidence": 0.7,
                        "reasoning": "person close to the drone",
                    }
                ),
                json.dumps(
                    {
                        "component": "rafa",
                        "event": "frame_pipeline_summary",
                        "frame_id": 1,
                        "total_ms": 123,
                        "navigation_ms": 45,
                    }
                ),
                json.dumps(
                    {
                        "event": "publish",
                        "channel": "navigation",
                        "summary": {"frame_id": 1, "action": "hover", "confidence": 0.7},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (log_dir / f"{run_id}-nav_interpreter.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "component": "nav_interpreter",
                        "event": "command_posted",
                        "command_type": "hover",
                        "response_status": "executed",
                    }
                ),
                json.dumps(
                    {
                        "component": "nav_interpreter",
                        "event": "navigation_executed",
                        "frame_id": 1,
                        "command_type": "hover",
                        "command_id": "cmd-1",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = build_report(log_dir, run_id)

    assert report.exists()
    html = report.read_text(encoding="utf-8")
    assert "BreachEye Run Report" in html
    assert "Decision Timeline" in html
    assert "hover" in html
    assert "person close to the drone" in html
    assert "total=123ms" in html
    assert (run_dir / "report" / "assets" / "frame-00000001.jpg").exists()
    assert (run_dir / "report" / "assets" / "frame-00000001.png").exists()
