"""Render a run's findings as Markdown and JSON reports.

Reports contain **facts only**. There are no headlines, summaries, or article
text — the "Potential Editorial Angles" line is deliberately left for the human
editor. Each newly free game is written out in the fixed layout from the project
brief so an editor can scan candidates at a glance and drill into the JSON for
the raw data.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from newsroom.compare import RunDiff
from newsroom.models import NewsEvent, UpcomingGame

logger = logging.getLogger(__name__)


def _money(value: float | None) -> str:
    """Format a price, or an em dash when it is unknown."""
    return f"{value:.2f}" if value is not None else "—"


def _when(value: datetime | None) -> str:
    """Format a timestamp as ISO-8601, or 'unknown' when absent."""
    return value.isoformat() if value is not None else "unknown"


def _candidate_block(event: NewsEvent) -> list[str]:
    """Render one newly free game in the NEW STORY CANDIDATE layout."""
    reasons = "\n".join(f"    - {reason}" for reason in event.confidence.reasons)
    return [
        "### NEW STORY CANDIDATE",
        "",
        f"- **Store:** {event.source.value}",
        f"- **Game:** {event.title}",
        f"- **Promotion:** {event.promotion_type.value}",
        f"- **Developer:** {event.developer or 'unknown'}",
        f"- **Publisher:** {event.publisher or 'unknown'}",
        f"- **Original MSRP:** {_money(event.original_price)}",
        f"- **Current Price:** {_money(event.current_price)}",
        f"- **Promotion Start:** {_when(event.promotion_start)}",
        f"- **Promotion End:** {_when(event.promotion_end)}",
        f"- **Confidence:** {event.confidence.score}",
        "- **Reason Detected:**",
        reasons,
        "- **Potential Editorial Angles:** _(left for the editor)_",
        f"- **Source URLs:** {event.url}",
    ]


def _short_line(event: NewsEvent) -> str:
    """A one-line summary used in the 'ending soon' section."""
    return (
        f"- {event.source.value}: {event.title} — ends {_when(event.promotion_end)} "
        f"(confidence {event.confidence.score})"
    )


def render_markdown(
    diff: RunDiff,
    generated_at: datetime,
    suppressed: int = 0,
    upcoming: list[UpcomingGame] | None = None,
) -> str:
    """Render the full Markdown report for a run.

    ``suppressed`` is the number of detections the quality gate hid from this
    report; it is noted for transparency (the full record is in the database).
    ``upcoming`` lists games announced to become free soon (a heads-up section).
    """
    lines: list[str] = [
        "# Newsroom — Free Game Report",
        "",
        f"Generated: {generated_at.isoformat()}",
        "",
        (
            f"Summary: {len(diff.new)} new, {len(diff.ending_soon)} ending soon, "
            f"{len(diff.expired)} no longer free."
        ),
        "",
    ]

    if suppressed:
        lines += [
            f"_{suppressed} lower-quality detection(s) suppressed by the quality "
            "gate; the full record is in the database._",
            "",
        ]

    if diff.new:
        lines += ["## New story candidates", ""]
        for event in diff.new:
            lines += _candidate_block(event)
            lines.append("")

    if diff.ending_soon:
        lines += ["## Ending soon", ""]
        lines += [_short_line(event) for event in diff.ending_soon]
        lines.append("")

    if diff.expired:
        lines += ["## No longer free", ""]
        lines += [f"- {event.source.value}: {event.title}" for event in diff.expired]
        lines.append("")

    if upcoming:
        lines += ["## Upcoming free games (heads-up)", ""]
        for game in upcoming:
            starts = game.starts.date().isoformat() if game.starts else "soon"
            lines.append(f"- {game.title} — free from {starts} ({game.url})")
        lines.append("")

    if not diff.has_changes and not upcoming:
        lines.append("_No changes detected this run._")

    return "\n".join(lines).rstrip() + "\n"


def build_report_data(
    diff: RunDiff,
    generated_at: datetime,
    suppressed: int = 0,
    upcoming: list[UpcomingGame] | None = None,
) -> dict[str, Any]:
    """Build the JSON-serialisable representation of a run's findings."""
    upcoming = upcoming or []
    return {
        "generated_at": generated_at.isoformat(),
        "summary": {
            "new": len(diff.new),
            "ending_soon": len(diff.ending_soon),
            "expired": len(diff.expired),
            "suppressed": suppressed,
            "upcoming": len(upcoming),
        },
        "new": [event.model_dump(mode="json") for event in diff.new],
        "ending_soon": [event.model_dump(mode="json") for event in diff.ending_soon],
        "expired": [event.model_dump(mode="json") for event in diff.expired],
        "upcoming": [
            {
                "title": game.title,
                "url": game.url,
                "starts": game.starts.isoformat() if game.starts else None,
            }
            for game in upcoming
        ],
    }


def write_reports(
    diff: RunDiff,
    reports_dir: Path,
    generated_at: datetime,
    suppressed: int = 0,
    upcoming: list[UpcomingGame] | None = None,
) -> tuple[Path, Path]:
    """Write timestamped Markdown and JSON reports and return their paths.

    Args:
        diff: The comparison result to render.
        reports_dir: Directory to write into; created if missing.
        generated_at: Timestamp used both in the report body and the filenames.
        suppressed: Count of detections hidden by the quality gate, for the note.
        upcoming: Games announced to become free soon (heads-up section).

    Returns:
        ``(markdown_path, json_path)``.
    """
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
    markdown_path = reports_dir / f"report-{stamp}.md"
    json_path = reports_dir / f"report-{stamp}.json"

    markdown_text = render_markdown(diff, generated_at, suppressed, upcoming)
    json_text = json.dumps(build_report_data(diff, generated_at, suppressed, upcoming), indent=2)

    markdown_path.write_text(markdown_text, encoding="utf-8")
    json_path.write_text(json_text, encoding="utf-8")

    # Stable paths that always point at the most recent run, for convenience.
    (reports_dir / "latest.md").write_text(markdown_text, encoding="utf-8")
    (reports_dir / "latest.json").write_text(json_text, encoding="utf-8")

    return markdown_path, json_path


def prune_old_reports(reports_dir: Path, retention_days: int) -> int:
    """Delete timestamped reports older than ``retention_days``.

    ``latest.md`` / ``latest.json`` are always kept. A retention of 0 disables
    pruning. Returns the number of files removed.
    """
    if retention_days <= 0 or not reports_dir.exists():
        return 0

    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    removed = 0
    for path in reports_dir.glob("report-*"):
        if path.suffix not in (".md", ".json"):
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        if modified < cutoff:
            try:
                path.unlink()
                removed += 1
            except OSError:
                logger.warning("Could not delete old report %s", path, exc_info=True)
    if removed:
        logger.info("Pruned %d report file(s) older than %d days", removed, retention_days)
    return removed
