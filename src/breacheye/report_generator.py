"""Post-flight building report generator.

Takes a BuildingReport and produces formatted output for terminal display.
Optionally calls Qwen 3-VL (via its OpenAI-compatible server) to generate
a natural-language narrative summary.
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from datetime import datetime, UTC
from typing import Any

from breacheye.report import BuildingReport


__all__ = ["ReportGenerator"]


class ReportGenerator:
    """Formats BuildingReport data for human consumption.

    Works standalone (structured text output) and optionally enhances the
    report with a Qwen-generated narrative when a server URL is configured.
    """

    def generate_text_report(self, report: BuildingReport) -> str:
        """Format a BuildingReport as human-readable text for terminal display."""
        lines: list[str] = []

        # ------------------------------------------------------------------ #
        # Header
        # ------------------------------------------------------------------ #
        lines.append("=" * 70)
        lines.append("BREACHEYE BUILDING ASSESSMENT REPORT")
        lines.append("=" * 70)
        lines.append(f"Report ID  : {report.report_id}")
        generated = datetime.fromtimestamp(report.generated_at, tz=UTC).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
        lines.append(f"Generated  : {generated}")

        # ------------------------------------------------------------------ #
        # Flight Stats
        # ------------------------------------------------------------------ #
        lines.append("")
        lines.append("FLIGHT STATS")
        lines.append("-" * 40)
        flight = report.flight
        lines.append(f"Run ID          : {flight.run_id}")
        start_dt = datetime.fromtimestamp(flight.start_time, tz=UTC).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
        end_dt = datetime.fromtimestamp(flight.end_time, tz=UTC).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
        lines.append(f"Start           : {start_dt}")
        lines.append(f"End             : {end_dt}")
        lines.append(f"Duration        : {flight.duration_s:.1f}s")
        lines.append(f"Frames Processed: {flight.frames_processed}")
        lines.append(f"Detections      : {flight.detections_total}")
        lines.append(f"Nav Decisions   : {flight.nav_decisions_total}")
        if flight.distance_estimate_m is not None:
            lines.append(f"Distance Est.   : {flight.distance_estimate_m:.1f} m")
        if flight.battery_start is not None and flight.battery_end is not None:
            usage = flight.battery_start - flight.battery_end
            lines.append(
                f"Battery         : {flight.battery_start}% -> {flight.battery_end}%"
                f" ({usage:+d}%)"
            )
        elif flight.battery_start is not None:
            lines.append(f"Battery Start   : {flight.battery_start}%")
        elif flight.battery_end is not None:
            lines.append(f"Battery End     : {flight.battery_end}%")

        # ------------------------------------------------------------------ #
        # Threat Assessment
        # ------------------------------------------------------------------ #
        lines.append("")
        lines.append("THREAT ASSESSMENT")
        lines.append("-" * 40)
        threats = report.threats
        lines.append(f"Total POIs: {threats.total_pois}")

        if threats.by_category:
            lines.append("By Category:")
            for category, count in sorted(threats.by_category.items()):
                lines.append(f"  {category:<12} {count}")

        if threats.by_threat_level:
            lines.append("By Threat Level:")
            level_order = ["HOT", "WARM", "CAUTION", "CLEAR", "INFO"]
            present = {k: v for k, v in threats.by_threat_level.items()}
            for level in level_order:
                if level in present:
                    lines.append(f"  {level:<12} {present[level]}")
            for level, count in sorted(present.items()):
                if level not in level_order:
                    lines.append(f"  {level:<12} {count}")

        if threats.high_priority_items:
            lines.append(f"High-Priority Items ({len(threats.high_priority_items)}):")
            for item in threats.high_priority_items:
                label = item.get("label", item.get("id", "unknown"))
                threat = item.get("threat_level", "")
                location = item.get("location", "")
                detail = f"[{threat}]" if threat else ""
                if location:
                    detail = f"{detail} @ {location}" if detail else f"@ {location}"
                lines.append(f"  * {label} {detail}".rstrip())

        # ------------------------------------------------------------------ #
        # Rooms
        # ------------------------------------------------------------------ #
        if report.rooms:
            lines.append("")
            lines.append("ROOM SUMMARY")
            lines.append("-" * 40)
            for room in report.rooms:
                lines.append(f"Room {room.room_id}:")
                lines.append(f"  Threat Level : {room.threat_level}")
                lines.append(f"  POI Count    : {room.poi_count}")
                lines.append(f"  Coverage     : {room.coverage_pct:.1f}%")
                if room.entry_points:
                    lines.append(f"  Entry Points : {', '.join(room.entry_points)}")
                if room.dimensions_estimate:
                    dims = ", ".join(
                        f"{k}={v}" for k, v in room.dimensions_estimate.items()
                    )
                    lines.append(f"  Dimensions   : {dims}")

        # ------------------------------------------------------------------ #
        # Recommendations
        # ------------------------------------------------------------------ #
        lines.append("")
        lines.append("RECOMMENDATIONS")
        lines.append("-" * 40)
        if report.recommended_entry:
            lines.append(f"Recommended Entry Point : {report.recommended_entry}")
        else:
            lines.append("Recommended Entry Point : N/A")

        if report.chokepoints:
            lines.append("Chokepoints:")
            for cp in report.chokepoints:
                lines.append(f"  * {cp}")
        else:
            lines.append("Chokepoints: none identified")

        # ------------------------------------------------------------------ #
        # Narrative (if present on the report object)
        # ------------------------------------------------------------------ #
        if report.narrative:
            lines.append("")
            lines.append("NARRATIVE SUMMARY")
            lines.append("-" * 40)
            lines.append(report.narrative)

        lines.append("")
        lines.append("=" * 70)

        return "\n".join(lines)

    async def generate_narrative(
        self,
        report: BuildingReport,
        keyframes: list[bytes] | None = None,
    ) -> str:
        """Generate a tactical narrative summary using Qwen 3-VL.

        Falls back to an auto-generated summary from structured data if Qwen
        is unavailable.

        Args:
            report: The BuildingReport to summarize.
            keyframes: Optional JPEG keyframes (currently unused; reserved for
                future multimodal support).

        Returns:
            A 3-5 sentence tactical narrative string.
        """
        server_url = os.environ.get("BREACHEYE_QWEN_SERVER_URL")
        if server_url:
            try:
                return await self._call_qwen_server(report, server_url)
            except Exception:
                pass

        return self._fallback_narrative(report)

    async def _call_qwen_server(
        self, report: BuildingReport, server_url: str
    ) -> str:
        """Call the Qwen OpenAI-compatible server for a narrative summary."""
        import asyncio

        report_context = _build_report_context(report)
        prompt = (
            "You are a tactical intelligence analyst. Based on the following building "
            "assessment data, provide a 3-5 sentence tactical summary including key "
            "threats, recommended approach, and areas of concern.\n\n"
            f"{report_context}"
        )
        payload = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": int(os.environ.get("BREACHEYE_QWEN_MAX_TOKENS", "256")),
        }
        request = urllib.request.Request(
            server_url.rstrip("/") + "/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"content-type": "application/json"},
        )
        timeout = float(os.environ.get("BREACHEYE_QWEN_TIMEOUT_S", "20"))

        def _call() -> str:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()

        return await asyncio.to_thread(_call)

    def _fallback_narrative(self, report: BuildingReport) -> str:
        """Generate a rule-based fallback narrative from structured data."""
        flight = report.flight
        threats = report.threats

        hot_count = threats.by_threat_level.get("HOT", 0)
        warm_count = threats.by_threat_level.get("WARM", 0)
        room_count = len(report.rooms)

        parts: list[str] = []

        # Sentence 1: flight overview
        parts.append(
            f"Flight {flight.run_id} completed in {flight.duration_s:.0f} seconds, "
            f"processing {flight.frames_processed} frames and recording "
            f"{threats.total_pois} points of interest."
        )

        # Sentence 2: threat summary
        if hot_count > 0:
            parts.append(
                f"Critical threat assessment: {hot_count} HOT and {warm_count} WARM "
                f"contacts identified — immediate tactical attention required."
            )
        elif warm_count > 0:
            parts.append(
                f"Elevated threat level: {warm_count} WARM contacts identified; "
                f"proceed with caution."
            )
        else:
            parts.append("No high-priority threats detected during this assessment.")

        # Sentence 3: rooms / areas
        if room_count > 0:
            covered = [r for r in report.rooms if r.coverage_pct >= 80.0]
            parts.append(
                f"{room_count} area{'s' if room_count != 1 else ''} assessed"
                + (
                    f", {len(covered)} with ≥80% coverage"
                    if covered
                    else ""
                )
                + "."
            )

        # Sentence 4: entry / chokepoints
        if report.recommended_entry:
            cp_note = ""
            if report.chokepoints:
                cp_note = (
                    f"; monitor chokepoint{'s' if len(report.chokepoints) != 1 else ''} "
                    + ", ".join(report.chokepoints)
                )
            parts.append(
                f"Recommended entry via {report.recommended_entry}{cp_note}."
            )
        elif report.chokepoints:
            parts.append(
                "Key chokepoints identified: "
                + ", ".join(report.chokepoints)
                + "."
            )

        return " ".join(parts)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _build_report_context(report: BuildingReport) -> str:
    """Serialize BuildingReport to a compact text block for the Qwen prompt."""
    flight = report.flight
    threats = report.threats
    lines: list[str] = [
        f"run_id={flight.run_id}",
        f"duration={flight.duration_s:.0f}s",
        f"frames={flight.frames_processed}",
        f"total_pois={threats.total_pois}",
        "by_threat_level=" + json.dumps(threats.by_threat_level),
        "by_category=" + json.dumps(threats.by_category),
    ]
    if report.rooms:
        room_summaries = [
            f"{r.room_id}:threat={r.threat_level},pois={r.poi_count},coverage={r.coverage_pct:.0f}%"
            for r in report.rooms
        ]
        lines.append("rooms=" + "; ".join(room_summaries))
    if report.recommended_entry:
        lines.append(f"recommended_entry={report.recommended_entry}")
    if report.chokepoints:
        lines.append("chokepoints=" + ", ".join(report.chokepoints))
    if threats.high_priority_items:
        items = [
            item.get("label", item.get("id", "?")) + f"[{item.get('threat_level', '')}]"
            for item in threats.high_priority_items
        ]
        lines.append("high_priority=" + "; ".join(items))
    return "\n".join(lines)
