from __future__ import annotations

import argparse
import html
import json
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an HTML report from a BreachEye offline run.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report_path = build_report(Path(args.log_dir), args.run_id, args.output)
    print(report_path)


def build_report(log_dir: Path, run_id: str, output: Path | None = None) -> Path:
    run_dir = log_dir / run_id
    report_dir = output or run_dir / "report"
    assets_dir = report_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    rafa_events = _read_jsonl(log_dir / f"{run_id}-rafa.jsonl")
    publisher_events = _read_jsonl(log_dir / f"{run_id}-frame_publisher.jsonl")
    metadata = _read_json(run_dir / "run-metadata.json")
    map_summary = _read_json(run_dir / "map" / "relative-depth-summary.json")

    frames = _frame_rows(run_dir, rafa_events)
    for row in frames:
        for key in ("drone_image", "depth_image"):
            if row.get(key):
                row[f"{key}_asset"] = _copy_asset(Path(row[key]), assets_dir)

    map_preview = run_dir / "map" / "relative-depth-topdown.png"
    map_preview_asset = _copy_asset(map_preview, assets_dir) if map_preview.exists() else None

    html_path = report_dir / "index.html"
    html_path.write_text(
        _render_html(
            run_id=run_id,
            metadata=metadata,
            map_summary=map_summary,
            map_preview=map_preview_asset,
            frames=frames,
            rafa_events=rafa_events,
            publisher_events=publisher_events,
        ),
        encoding="utf-8",
    )
    return html_path


def _frame_rows(run_dir: Path, rafa_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = defaultdict(dict)
    for path in sorted((run_dir / "rafa" / "frames").glob("frame-*.jpg")):
        frame_id = _frame_id(path)
        rows[frame_id]["frame_id"] = frame_id
        rows[frame_id]["drone_image"] = str(path)
    for path in sorted((run_dir / "rafa" / "depth").glob("frame-*.png")):
        frame_id = _frame_id(path)
        rows[frame_id]["frame_id"] = frame_id
        rows[frame_id]["depth_image"] = str(path)
    for event in rafa_events:
        if event.get("event") == "publish" and event.get("channel") == "navigation":
            summary = event.get("summary", {})
            frame_id = summary.get("frame_id")
            if isinstance(frame_id, int):
                rows[frame_id]["frame_id"] = frame_id
                rows[frame_id]["action"] = summary.get("action")
                rows[frame_id]["confidence"] = summary.get("confidence")
                rows[frame_id]["timestamp"] = summary.get("timestamp")
    return [rows[key] for key in sorted(rows)]


def _render_html(
    *,
    run_id: str,
    metadata: dict[str, Any],
    map_summary: dict[str, Any],
    map_preview: str | None,
    frames: list[dict[str, Any]],
    rafa_events: list[dict[str, Any]],
    publisher_events: list[dict[str, Any]],
) -> str:
    nav_actions = [row.get("action", "missing") for row in frames]
    processed = len([row for row in frames if row.get("action")])
    received = len([event for event in rafa_events if event.get("event") == "frame_received"])
    published = len([event for event in publisher_events if event.get("event") == "frame_published"])
    depth_images = len([row for row in frames if row.get("depth_image")])
    model_event = next((event for event in rafa_events if event.get("event") == "configure_adapters_done"), {})
    fallbacks = [event for event in rafa_events if "fallback" in str(event.get("event", ""))]

    frame_cards = "\n".join(_frame_card(row) for row in frames)
    fallback_items = "\n".join(
        f"<li><code>{_esc(item.get('model', item.get('event')))}</code>: {_esc(item.get('error', ''))}</li>"
        for item in fallbacks
    ) or "<li>None</li>"
    map_html = (
        f'<img class="map" src="{_esc(map_preview)}" alt="Relative depth top-down map">'
        if map_preview
        else "<p>No map preview generated.</p>"
    )
    models = json.dumps(model_event.get("models", {}), indent=2, sort_keys=True)
    env = metadata.get("env", {})

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BreachEye Run Report - {_esc(run_id)}</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #172026; background: #f5f7f8; }}
    header {{ padding: 28px 36px; background: #172026; color: white; }}
    main {{ padding: 28px 36px 48px; max-width: 1400px; margin: 0 auto; }}
    h1, h2, h3 {{ margin: 0 0 12px; letter-spacing: 0; }}
    .subtle {{ color: #607078; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 18px 0 28px; }}
    .metric {{ background: white; border: 1px solid #dde3e6; border-radius: 8px; padding: 14px; }}
    .metric strong {{ display: block; font-size: 28px; margin-bottom: 4px; }}
    section {{ margin: 0 0 32px; }}
    .frame-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }}
    .frame {{ background: white; border: 1px solid #dde3e6; border-radius: 8px; overflow: hidden; }}
    .frame-body {{ padding: 12px; }}
    .pair {{ display: grid; grid-template-columns: 1fr 1fr; gap: 2px; background: #dde3e6; }}
    img {{ width: 100%; display: block; object-fit: cover; }}
    .pair img {{ aspect-ratio: 16 / 9; }}
    .map {{ max-width: 760px; border: 1px solid #dde3e6; border-radius: 8px; background: white; }}
    code, pre {{ background: #edf1f3; border-radius: 6px; }}
    pre {{ overflow: auto; padding: 12px; }}
    .pill {{ display: inline-block; padding: 4px 8px; border-radius: 999px; background: #e8f1ee; color: #164734; font-weight: 600; }}
    ul {{ margin-top: 8px; }}
  </style>
</head>
<body>
  <header>
    <h1>BreachEye Run Report</h1>
    <div class="subtle">{_esc(run_id)}</div>
  </header>
  <main>
    <section>
      <h2>Summary</h2>
      <div class="grid">
        <div class="metric"><strong>{published}</strong><span>frames published</span></div>
        <div class="metric"><strong>{received}</strong><span>frames processed</span></div>
        <div class="metric"><strong>{depth_images}</strong><span>depth images</span></div>
        <div class="metric"><strong>{_esc(map_summary.get("points", "n/a"))}</strong><span>map points</span></div>
      </div>
      <p><span class="pill">Actions</span> {_esc(", ".join(str(action) for action in nav_actions))}</p>
    </section>

    <section>
      <h2>What The Drone Saw And Decided</h2>
      <div class="frame-grid">
        {frame_cards}
      </div>
    </section>

    <section>
      <h2>Relative 3D Map Preview</h2>
      {map_html}
      <p class="subtle">Generated from saved relative depth arrays. This is qualitative, not metric reconstruction.</p>
    </section>

    <section>
      <h2>Model State</h2>
      <pre>{_esc(models)}</pre>
      <h3>Fallbacks</h3>
      <ul>{fallback_items}</ul>
    </section>

    <section>
      <h2>Environment</h2>
      <pre>{_esc(json.dumps(env, indent=2, sort_keys=True))}</pre>
    </section>
  </main>
</body>
</html>
"""


def _frame_card(row: dict[str, Any]) -> str:
    frame_id = row.get("frame_id", "?")
    drone_img = row.get("drone_image_asset")
    depth_img = row.get("depth_image_asset")
    image_html = f"""
      <div class="pair">
        {_image_or_blank(drone_img, "Drone frame")}
        {_image_or_blank(depth_img, "Depth image")}
      </div>
    """
    return f"""
    <article class="frame">
      {image_html}
      <div class="frame-body">
        <h3>Frame {_esc(frame_id)}</h3>
        <p><strong>Decision:</strong> {_esc(row.get("action", "missing"))}</p>
        <p><strong>Confidence:</strong> {_esc(row.get("confidence", "n/a"))}</p>
      </div>
    </article>
    """


def _image_or_blank(src: str | None, alt: str) -> str:
    if not src:
        return "<div></div>"
    return f'<img src="{_esc(src)}" alt="{_esc(alt)}">'


def _copy_asset(path: Path, assets_dir: Path) -> str:
    target = assets_dir / path.name
    if target.exists():
        target = assets_dir / f"{path.parent.name}-{path.name}"
    shutil.copy2(path, target)
    return str(target.relative_to(assets_dir.parent))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _frame_id(path: Path) -> int:
    return int(path.stem.split("-")[-1])


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


if __name__ == "__main__":
    main()
