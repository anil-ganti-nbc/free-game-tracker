"""Prospective, durable FreeGameFindings community-lead delivery."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from alembic import command
from alembic.config import Config
from clank_reddit import RedditUnavailable, parse_listing
from newsroom import database as db
from newsroom import discovery_delivery as leads
from newsroom.cli import run_pipeline
from newsroom.config import PROJECT_ROOT, settings
from newsroom.discovery import collect
from newsroom.tests.test_reddit_admission import listing


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "database_path", tmp_path / "newsroom.db")
    monkeypatch.setattr(settings, "reports_dir", tmp_path / "reports")
    monkeypatch.setattr(settings, "enable_reddit_fgf_delivery", False)
    monkeypatch.setattr(settings, "enable_reddit_discovery", True)
    monkeypatch.setattr(settings, "discord_webhook_url", None)
    db.reset_engine()
    db.init_db()
    yield
    db.reset_engine()


def page(*ids: str, title: str = "[Steam] (Game) Example") -> tuple[int, str]:
    return 200, listing(ids=tuple(ids), title=title)


def rows() -> list[db.DiscoveryDeliveryRow]:
    with db.session_scope() as session:
        return list(session.scalars(select(db.DiscoveryDeliveryRow)))


def latest_run_evidence() -> dict[str, object]:
    with db.session_scope() as session:
        run = session.scalar(select(db.DiscoveryRunRow).order_by(db.DiscoveryRunRow.id.desc()))
        assert run is not None
        return run.evidence


def assert_planes(result: dict[str, object], lead_authority: str, intents: int) -> None:
    assert result["news_event_delivery"] == "blocked"
    assert result["community_lead_delivery"] == lead_authority
    assert result["new_intents"] == intents
    assert "delivery" not in result


def seed_new(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enable_reddit_fgf_delivery", True)
    collect(leads.FGF_SOURCE, get=lambda _: page("baseline"))
    collect(leads.FGF_SOURCE, get=lambda _: page("new", "baseline"), code_revision="test-sha")


def test_baseline_and_flag_off_never_backfill(
    isolated: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "enable_reddit_fgf_delivery", True)
    collect(leads.FGF_SOURCE, get=lambda _: page("baseline"))
    assert rows() == []
    monkeypatch.setattr(settings, "enable_reddit_fgf_delivery", False)
    off = collect(leads.FGF_SOURCE, get=lambda _: page("old", "baseline"))
    assert_planes(off, "disabled", 0)
    assert_planes(latest_run_evidence(), "disabled", 0)
    assert rows() == []
    monkeypatch.setattr(settings, "enable_reddit_fgf_delivery", True)
    collect(leads.FGF_SOURCE, get=lambda _: page("old", "baseline"))
    assert rows() == []
    enabled = collect(leads.FGF_SOURCE, get=lambda _: page("new", "old", "baseline"))
    assert_planes(enabled, "authorized", 1)
    assert_planes(latest_run_evidence(), "authorized", 1)
    assert [r.external_id for r in rows()] == ["t3_new"]


def test_eligible_intent_provenance_and_replay(
    isolated: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_new(monkeypatch)
    intent = rows()[0]
    assert intent.status == "pending" and intent.attempts == 0
    assert intent.observation_key == "reddit_free_game_findings:t3_new"
    assert intent.classification == "giveaway_claim_unverified"
    assert intent.classification_policy == leads.FGF_POLICY
    assert intent.code_revision == "test-sha"
    assert len(intent.raw_sha256) == 64
    original_payload = intent.payload
    collect(leads.FGF_SOURCE, get=lambda _: page("baseline", "new", title="[Steam] (DLC) Edited"))
    db.reset_engine()
    collect(leads.FGF_SOURCE, get=lambda _: page("new", "baseline"))
    assert len(rows()) == 1 and rows()[0].payload == original_payload


def test_negative_v1_intel_and_dry_run_suppressed(
    isolated: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "enable_reddit_fgf_delivery", True)
    collect(leads.FGF_SOURCE, get=lambda _: page("base"))
    negative = collect(
        leads.FGF_SOURCE, get=lambda _: page("negative", "base", title="[PSA] Giveaway")
    )
    assert_planes(negative, "authorized", 0)
    assert_planes(latest_run_evidence(), "authorized", 0)
    dry = collect(leads.FGF_SOURCE, get=lambda _: page("dry", "base"), persist=False)
    assert_planes(dry, "authorized", 0)
    assert rows() == []
    with db.session_scope() as session:
        old = session.get(db.DiscoveryObservationRow, "reddit_free_game_findings:t3_base")
        assert old is not None
        old.evidence = [{**old.evidence[0], "classification_policy": "fgt-reddit-discovery-v1"}]
    collect(leads.FGF_SOURCE, get=lambda _: page("base"))
    intel = collect(
        "reddit_gaming_leaks",
        get=lambda _: (200, listing(community="GamingLeaksAndRumours", ids=("intelbase",))),
    )
    assert_planes(intel, "disabled", 0)
    assert_planes(latest_run_evidence(), "disabled", 0)
    intel_new = collect(
        "reddit_gaming_leaks",
        get=lambda _: (
            200,
            listing(community="GamingLeaksAndRumours", ids=("intelnew", "intelbase")),
        ),
    )
    assert_planes(intel_new, "disabled", 0)
    assert_planes(latest_run_evidence(), "disabled", 0)
    assert rows() == []


def test_missing_webhook_no_notify_failure_and_success(
    isolated: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_new(monkeypatch)
    assert leads.drain_leads()["reddit_leads_pending"] == 1
    assert rows()[0].attempts == 0
    sent: list[dict[str, object]] = []

    def send(_url: str, payload: dict[str, object]) -> bool:
        sent.append(payload)
        return len(sent) > 1

    outcome = leads.drain_leads(send=send, webhook_url="https://discord.test/webhook")
    assert outcome["reddit_leads_failed"] == 1
    assert rows()[0].status == "failed" and rows()[0].attempts == 1
    assert rows()[0].delivered_at is None
    outcome = leads.drain_leads(send=send, webhook_url="https://discord.test/webhook")
    assert outcome["reddit_leads_posted"] == 1
    assert rows()[0].status == "delivered" and rows()[0].attempts == 2
    assert rows()[0].delivered_at is not None
    visible = db.load_discovery_observations()
    assert visible[0]["community_lead_outbox_status"] == "delivered"
    db.reset_engine()
    assert (
        leads.drain_leads(send=send, webhook_url="https://discord.test/webhook")[
            "reddit_leads_posted"
        ]
        == 0
    )
    assert len(sent) == 2


def test_payload_wording_permalink_and_limits() -> None:
    permalink = "https://www.reddit.com/r/FreeGameFindings/comments/abc/story/"
    payload = leads.build_lead_payload("X" * 1000, permalink, datetime(2026, 9, 23, tzinfo=UTC))
    assert payload["content"] == "Reddit community lead — unverified giveaway claim"
    assert "confirmed" not in str(payload).lower()
    assert "new free game detected" not in str(payload).lower()
    embed = payload["embeds"][0]
    assert len(embed["title"]) == 256
    assert embed["url"] == permalink
    assert {f["value"] for f in embed["fields"]} >= {
        "r/FreeGameFindings",
        "Unverified community claim",
    }
    assert payload["allowed_mentions"] == {"parse": []}


def test_invalid_payload_is_held_once(isolated: None, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_new(monkeypatch)
    with db.session_scope() as session:
        row = session.get(db.DiscoveryDeliveryRow, "reddit_free_game_findings:t3_new")
        assert row is not None
        row.payload = {"content": "malformed"}
    called: list[int] = []

    def send(_url: str, _payload: dict[str, object]) -> bool:
        called.append(1)
        return True

    outcome = leads.drain_leads(
        send=send,
        webhook_url="https://discord.test/webhook",
    )
    assert outcome["reddit_leads_held"] == 1 and not called
    assert rows()[0].status == "held" and rows()[0].attempts == 0


def test_no_notify_keeps_intent_and_no_discord(
    isolated: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "enable_reddit_fgf_delivery", True)
    collect(leads.FGF_SOURCE, get=lambda _: page("base"))
    # Use a real collection result while all ordinary sources are deselected.
    monkeypatch.setattr(
        "newsroom.sources.reddit.fetch",
        lambda _source, _get=None: parse_listing(page("new", "base")[1], "FreeGameFindings"),
    )
    monkeypatch.setattr(
        "newsroom.notify.post_discord",
        lambda *_args, **_kwargs: pytest.fail("Discord called under --no-notify"),
    )
    result = run_pipeline(
        selected=[leads.FGF_SOURCE], include_breakouts=False, include_deals=False, do_notify=False
    )
    assert result["reddit_leads_pending"] == 1
    assert result["reddit_leads_posted"] == 0
    assert_planes(result["discovery"][leads.FGF_SOURCE], "authorized", 1)
    assert rows()[0].status == "pending"


def test_discord_failure_is_isolated_from_normal_run(
    isolated: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "enable_reddit_fgf_delivery", True)
    monkeypatch.setattr(settings, "discord_webhook_url", "https://discord.test/webhook")
    collect(leads.FGF_SOURCE, get=lambda _: page("base"))
    monkeypatch.setattr(
        "newsroom.sources.reddit.fetch",
        lambda _source, _get=None: parse_listing(page("new", "base")[1], "FreeGameFindings"),
    )
    monkeypatch.setattr("newsroom.notify.post_discord", lambda *_args, **_kwargs: False)
    result = run_pipeline(selected=[leads.FGF_SOURCE], include_breakouts=False, include_deals=False)
    assert result["reddit_leads_detected"] == 1
    assert result["reddit_leads_eligible"] == 1
    assert result["reddit_leads_failed"] == 1
    assert result["reddit_leads_pending"] == 1
    assert_planes(result["discovery"][leads.FGF_SOURCE], "authorized", 1)
    assert result["discord_detected"] == 0
    assert rows()[0].status == "failed" and rows()[0].attempts == 1


def test_transaction_rolls_back_observation_if_intent_cannot_be_built(
    isolated: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "enable_reddit_fgf_delivery", True)
    collect(leads.FGF_SOURCE, get=lambda _: page("base"))
    monkeypatch.setattr(
        leads, "build_lead_payload", lambda *_args: (_ for _ in ()).throw(ValueError("bad"))
    )
    with pytest.raises(ValueError, match="bad"):
        collect(leads.FGF_SOURCE, get=lambda _: page("new", "base"))
    assert rows() == []
    with db.session_scope() as session:
        observations = list(session.scalars(select(db.DiscoveryObservationRow)))
        runs = list(session.scalars(select(db.DiscoveryRunRow).order_by(db.DiscoveryRunRow.id)))
    assert len(observations) == 1 and observations[0].external_id == "t3_base"
    assert [r.status for r in runs] == ["ok", "failed"]


def test_drain_is_bounded_per_run(isolated: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enable_reddit_fgf_delivery", True)
    collect(leads.FGF_SOURCE, get=lambda _: page("base"))
    ids = tuple(f"n{i}" for i in range(11))
    collect(leads.FGF_SOURCE, get=lambda _: page(*ids, "base"))
    sent: list[int] = []

    def accept(_url: str, _payload: dict[str, object]) -> bool:
        sent.append(1)
        return True

    first = leads.drain_leads(send=accept, webhook_url="https://discord.test/webhook")
    assert first["reddit_leads_posted"] == 10 and first["reddit_leads_pending"] == 1
    second = leads.drain_leads(send=accept, webhook_url="https://discord.test/webhook")
    assert second["reddit_leads_posted"] == 1 and second["reddit_leads_pending"] == 0
    assert len(sent) == 11


def test_reddit_403_fails_closed_and_ordinary_run_survives(
    isolated: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "enable_reddit_fgf_delivery", True)
    monkeypatch.setattr(
        "newsroom.sources.reddit.fetch",
        lambda _source, _get=None: (_ for _ in ()).throw(
            RedditUnavailable("Reddit HTTP 403; intake not completed")
        ),
    )
    result = run_pipeline(
        selected=[leads.FGF_SOURCE], include_breakouts=False, include_deals=False, do_notify=False
    )
    assert result["discovery"][leads.FGF_SOURCE]["error"] == (
        "Reddit HTTP 403; intake not completed"
    )
    assert_planes(result["discovery"][leads.FGF_SOURCE], "authorized", 0)
    assert result["reddit_leads_posted"] == 0
    assert result["reddit_leads_failed"] == 0
    assert result["reddit_leads_pending"] == 0
    assert rows() == []
    with db.session_scope() as session:
        runs = list(session.scalars(select(db.DiscoveryRunRow)))
    assert len(runs) == 1 and runs[0].status == "failed"
    assert_planes(runs[0].evidence, "authorized", 0)
    assert db.load_all_events() == []


def test_upgrade_preserves_history_without_backlog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "database_path", tmp_path / "upgrade.db")
    monkeypatch.setattr(settings, "enable_reddit_fgf_delivery", True)
    db.reset_engine()
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(cfg, "e102_discovery")
    now = datetime(2026, 9, 22, tzinfo=UTC)
    evidence = [{"classification_policy": "fgt-reddit-discovery-v1", "raw_sha256": "old"}]
    with db.session_scope() as session:
        session.add(
            db.NewsEventRow(
                event_key="epic:historical",
                source="epic",
                category="game_promotion",
                title="Historical game",
                url="https://example.com/game",
                promotion_type="giveaway",
                discovered_at=now,
                last_seen=now,
                confidence_score=100,
                confidence_reasons=[],
                event_metadata={},
            )
        )
        session.add(
            db.DiscoveryRunRow(
                source=leads.FGF_SOURCE,
                started_at=now,
                finished_at=now,
                status="ok",
                baseline=True,
                evidence={"code_revision": "old", "delivery": "blocked"},
            )
        )
        session.add(
            db.DiscoveryObservationRow(
                key="reddit_free_game_findings:t3_historical",
                source=leads.FGF_SOURCE,
                external_id="t3_historical",
                title="[Steam] (Game) Historical",
                url="https://www.reddit.com/r/FreeGameFindings/comments/historical/story/",
                classification="non_game_or_unclassified",
                baseline=True,
                first_seen=now,
                last_seen=now,
                evidence=evidence,
            )
        )
    command.upgrade(cfg, "head")
    with db.session_scope() as session:
        assert session.scalar(select(db.NewsEventRow.event_key)) == "epic:historical"
        old_run = session.scalar(select(db.DiscoveryRunRow))
        assert old_run is not None and old_run.source == leads.FGF_SOURCE
        assert old_run.evidence == {"code_revision": "old", "delivery": "blocked"}
        old = session.get(db.DiscoveryObservationRow, "reddit_free_game_findings:t3_historical")
        assert old is not None
        assert old.evidence == evidence and old.classification == "non_game_or_unclassified"
        assert old.first_seen == now and old.baseline
        assert list(session.scalars(select(db.DiscoveryDeliveryRow))) == []
    collect(leads.FGF_SOURCE, get=lambda _: page("historical"))
    assert_planes(latest_run_evidence(), "authorized", 0)
    with db.session_scope() as session:
        old_run = session.scalar(select(db.DiscoveryRunRow).order_by(db.DiscoveryRunRow.id))
        assert old_run is not None
        assert old_run.evidence == {"code_revision": "old", "delivery": "blocked"}
    assert rows() == []
    db.reset_engine()
