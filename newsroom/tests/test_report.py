"""Tests for Markdown and JSON report rendering."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from newsroom.compare import RunDiff, compare
from newsroom.models import Confidence, NewsEvent, PromotionType, Source
from newsroom.report import (
    build_report_data,
    prune_old_reports,
    render_markdown,
    write_reports,
)

GENERATED_AT = datetime(2026, 7, 19, 18, 30, tzinfo=UTC)


def _event(url: str = "https://store.epicgames.com/en-US/p/x") -> NewsEvent:
    return NewsEvent(
        source=Source.EPIC,
        title="Sample Free Game",
        url=url,
        developer="Sample Studio",
        publisher="Sample Publisher",
        promotion_type=PromotionType.GIVEAWAY,
        original_price=19.99,
        current_price=0.0,
        promotion_end=datetime(2026, 7, 25, tzinfo=UTC),
        confidence=Confidence(score=100, reasons=["MSRP changed from paid to free"]),
    )


def test_markdown_contains_candidate_facts() -> None:
    diff = RunDiff(new=[_event()])
    text = render_markdown(diff, GENERATED_AT)
    assert "NEW STORY CANDIDATE" in text
    assert "Sample Free Game" in text
    assert "19.99" in text
    assert "MSRP changed from paid to free" in text
    assert "Potential Editorial Angles" in text
    # Facts only — no invented headline text.
    assert "Sample Publisher" in text


def test_markdown_reports_no_changes() -> None:
    text = render_markdown(RunDiff(), GENERATED_AT)
    assert "No changes detected" in text


def test_json_structure_and_counts() -> None:
    soon = _event("https://store.epicgames.com/en-US/p/soon")
    diff = RunDiff(new=[_event()], ending_soon=[soon])
    data = build_report_data(diff, GENERATED_AT)
    assert data["summary"] == {
        "new": 1,
        "ending_soon": 1,
        "expired": 0,
        "suppressed": 0,
        "upcoming": 0,
    }
    assert data["new"][0]["title"] == "Sample Free Game"
    assert data["new"][0]["confidence"]["score"] == 100
    assert data["generated_at"] == GENERATED_AT.isoformat()


def test_write_reports_creates_both_files(tmp_path: Path) -> None:
    diff = RunDiff(new=[_event()])
    md_path, json_path = write_reports(diff, tmp_path / "reports", GENERATED_AT)
    assert md_path.exists()
    assert json_path.exists()
    # The JSON round-trips.
    parsed = json.loads(json_path.read_text(encoding="utf-8"))
    assert parsed["summary"]["new"] == 1


def test_prune_removes_old_reports_but_keeps_latest_and_recent(tmp_path: Path) -> None:
    import os
    import time

    reports = tmp_path / "reports"
    reports.mkdir()
    old_md = reports / "report-20200101T000000Z.md"
    old_json = reports / "report-20200101T000000Z.json"
    recent_md = reports / "report-20260719T000000Z.md"
    latest = reports / "latest.md"
    for f in (old_md, old_json, recent_md, latest):
        f.write_text("x", encoding="utf-8")
    # Age the old files well past the retention window.
    old_ts = time.time() - 60 * 24 * 3600
    os.utime(old_md, (old_ts, old_ts))
    os.utime(old_json, (old_ts, old_ts))

    removed = prune_old_reports(reports, retention_days=30)
    assert removed == 2
    assert not old_md.exists()
    assert not old_json.exists()
    assert recent_md.exists()
    assert latest.exists()  # never pruned


def test_prune_disabled_when_zero(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "report-20200101T000000Z.md").write_text("x", encoding="utf-8")
    assert prune_old_reports(reports, retention_days=0) == 0


def test_ending_soon_section_included_for_continuing_event(tmp_path: Path) -> None:
    end = datetime.now(UTC) + timedelta(hours=6)
    prior = NewsEvent(
        source=Source.EPIC,
        title="Continuing Game",
        url="https://store.epicgames.com/en-US/p/cont",
        promotion_type=PromotionType.GIVEAWAY,
        original_price=9.99,
        current_price=0.0,
        promotion_end=end,
        confidence=Confidence(score=70, reasons=["ending"]),
    )
    diff = compare([prior], [prior], ending_soon_hours=48)
    text = render_markdown(diff, GENERATED_AT)
    assert "Ending soon" in text
    assert "Continuing Game" in text
