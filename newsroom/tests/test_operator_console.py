"""Regression tests for the operator console (run controls, health, empty states).

These lock down the behaviour the dashboard is *for*, and in particular the
governing invariant of this application: **rendering the GUI must never start a
collection.** Collection is an explicit operator act and nothing else.

Everything here is deterministic and offline — sources are replaced with local
stubs, so no test in this file can reach the network.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from newsroom import cli, database, run_lock, webapp
from newsroom.config import settings
from newsroom.database import SourceHealth
from newsroom.models import Confidence, NewsEvent, PromotionType, Source
from newsroom.sources import epic


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setattr(settings, "database_path", tmp_path / "test.db")
    monkeypatch.setattr(settings, "reports_dir", tmp_path / "reports")
    # Keep the pipeline network-silent and side-effect free beyond the temp DB.
    monkeypatch.setattr(settings, "discord_webhook_url", None)
    monkeypatch.setattr(settings, "enable_breakouts", False)
    monkeypatch.setattr(settings, "enable_deals", False)
    # Epic's "upcoming" heads-up is fetched from the real module rather than
    # through _SOURCES, so stubbing _SOURCES alone would still leave one live
    # HTTP call in every run. Stub it out so these tests are truly offline.
    monkeypatch.setattr(epic, "fetch_upcoming_free_games", lambda: [])
    database.reset_engine()
    database.init_db()
    webapp._RUN_STATE.update(
        status="idle", scope=None, started_at=None, finished_at=None,
        outcome=None, message=None, summary=None,
    )
    yield tmp_path
    database.reset_engine()


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A client with the operator profile installed, as `newsroom serve` does."""
    webapp.app.state.phase0_mutation_authorizer = lambda: True
    yield TestClient(webapp.app)
    webapp.app.state.phase0_mutation_authorizer = None


def _event(title: str = "Stub Game") -> NewsEvent:
    return NewsEvent(
        source=Source.EPIC,
        title=title,
        url="https://store.epicgames.com/en-US/p/stub",
        promotion_type=PromotionType.GIVEAWAY,
        original_price=24.99,
        current_price=0.0,
        promotion_end=datetime.now(UTC) + timedelta(days=5),
        confidence=Confidence(score=100, reasons=["price is 0"]),
    )


class _Spy:
    """A source stand-in that records whether it was ever invoked."""

    def __init__(self, events: list[NewsEvent] | None = None, boom: str | None = None) -> None:
        self.calls = 0
        self._events = events or []
        self._boom = boom

    def __call__(self) -> list[NewsEvent]:
        self.calls += 1
        if self._boom:
            raise RuntimeError(self._boom)
        return list(self._events)


# --------------------------------------------------------------------------
# M — a GUI GET never runs collectors
# --------------------------------------------------------------------------


def test_m_gui_get_never_runs_collectors(
    env: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rendering the page, or any read endpoint, must not touch a source.

    This is the invariant the whole design hangs off: a refresh, a poll, or a
    bookmark opening at 3am must never cause outbound crawling.
    """
    spy = _Spy([_event()])
    monkeypatch.setattr(cli, "_SOURCES", {"epic": spy})

    for path in ("/", "/api/state", "/api/runs"):
        assert client.get(path).status_code == 200

    assert spy.calls == 0
    # No collection means no health record and no stored event either.
    assert database.load_source_health() == []
    assert database.load_all_events() == []


def test_m_repeated_state_polls_stay_read_only(
    env: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The page polls /api/state on a timer; polling must stay inert."""
    spy = _Spy([_event()])
    monkeypatch.setattr(cli, "_SOURCES", {"epic": spy})
    for _ in range(5):
        client.get("/api/state")
    assert spy.calls == 0


# --------------------------------------------------------------------------
# N — an explicit run invokes the canonical collection path
# --------------------------------------------------------------------------


def test_n_explicit_run_invokes_canonical_pipeline(
    env: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /api/run goes through newsroom.cli.run_pipeline, not a UI copy."""
    seen: dict[str, Any] = {}
    real = cli.run_pipeline

    def _spy_pipeline(**kwargs: Any) -> dict[str, Any]:
        seen.update(kwargs)
        return real(**kwargs)

    spy = _Spy([_event()])
    monkeypatch.setattr(cli, "_SOURCES", {"epic": spy})
    monkeypatch.setattr(webapp, "run_pipeline", _spy_pipeline)

    resp = client.post("/api/run")
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True
    assert spy.calls == 1
    assert seen["include_sources"] is True
    # The run really persisted through the normal storage path.
    assert [e.title for e in database.load_all_events()] == ["Stub Game"]


def test_n_per_source_run_is_scoped_to_that_source(
    env: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    epic_spy = _Spy([_event("Epic Game")])
    gog_spy = _Spy([_event("GOG Game")])
    monkeypatch.setattr(cli, "_SOURCES", {"epic": epic_spy, "gog": gog_spy})

    resp = client.post("/api/run", json={"sources": ["epic"]})
    assert resp.status_code == 200, resp.text
    assert epic_spy.calls == 1
    assert gog_spy.calls == 0


def test_n_run_refuses_a_source_that_is_not_runnable(
    env: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The UI can never implicitly enable a disabled or unwired source."""
    monkeypatch.setattr(cli, "_SOURCES", {"epic": _Spy([_event()])})
    # amazon_luna exists as a module but is deliberately not wired in.
    resp = client.post("/api/run", json={"sources": ["amazon_luna"]})
    assert resp.status_code == 400
    assert "not runnable" in resp.json()["error"]

    # A source switched off by configuration is refused for the same reason.
    resp = client.post("/api/run", json={"sources": ["steam_deals"]})
    assert resp.status_code == 400


def test_n_run_requires_the_operator_profile(
    env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without the profile `newsroom serve` installs, running is refused."""
    spy = _Spy([_event()])
    monkeypatch.setattr(cli, "_SOURCES", {"epic": spy})
    webapp.app.state.phase0_mutation_authorizer = None
    with TestClient(webapp.app) as anon:
        assert anon.post("/api/run").status_code == 403
    assert spy.calls == 0


# --------------------------------------------------------------------------
# O — source status updates after a run
# --------------------------------------------------------------------------


def test_o_source_status_updates_after_a_run(
    env: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cli, "_SOURCES", {"epic": _Spy([_event()]), "gog": _Spy(boom="parser died")}
    )

    before = {s["name"]: s for s in client.get("/api/state").json()["sources"]}
    assert before["epic"]["status"] == "never_run"
    assert before["epic"]["last_success_at"] is None

    assert client.post("/api/run").status_code == 200

    after = {s["name"]: s for s in client.get("/api/state").json()["sources"]}
    assert after["epic"]["status"] == "ok"
    assert after["epic"]["last_success_at"] is not None
    assert after["epic"]["items"] == 1
    # A failing source is reported as failed, with its cause.
    assert after["gog"]["status"] == "error"
    assert "parser died" in (after["gog"]["error"] or "")
    assert after["gog"]["last_success_at"] is None


def test_o_zero_items_is_not_unhealthy(
    env: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A source that answers correctly with nothing is healthy, not broken."""
    monkeypatch.setattr(cli, "_SOURCES", {"epic": _Spy([])})
    assert client.post("/api/run").status_code == 200

    epic = {s["name"]: s for s in client.get("/api/state").json()["sources"]}["epic"]
    assert epic["status"] == "ok"
    assert epic["items"] == 0
    assert epic["error"] is None


# --------------------------------------------------------------------------
# P — no-data / zero-results / failed are three distinct states
# --------------------------------------------------------------------------


def _health(name: str, *, status: str, success: bool, count: int = 0) -> SourceHealth:
    now = datetime.now(UTC)
    return SourceHealth(
        source=name,
        last_attempt_at=now,
        last_success_at=now if success else None,
        last_status=status,
        last_count=count,
        last_error=None if status == "ok" else f"{name} exploded",
    )


def _sources_for(*health: SourceHealth) -> list[dict[str, Any]]:
    return webapp.build_sources(list(health), set())


def test_p_no_data_is_distinct_from_zero_results_and_failure(env: Path) -> None:
    names = webapp.SECTION_SOURCES["giveaways"]

    never = webapp.section_state("giveaways", _sources_for(), 0)
    assert never["state"] == "no_data"

    ok_zero = webapp.section_state(
        "giveaways",
        _sources_for(*[_health(n, status="ok", success=True) for n in names]),
        0,
    )
    assert ok_zero["state"] == "zero_results"

    all_failed = webapp.section_state(
        "giveaways",
        _sources_for(*[_health(n, status="error", success=False) for n in names]),
        0,
    )
    assert all_failed["state"] == "failed"
    assert "epic exploded" in all_failed["detail"]

    # And all three are genuinely different values, not aliases.
    assert len({never["state"], ok_zero["state"], all_failed["state"]}) == 3


def test_p_partial_failure_is_its_own_state(env: Path) -> None:
    health = [
        _health("epic", status="ok", success=True, count=1),
        _health("steam", status="error", success=False),
    ]
    sec = webapp.section_state("giveaways", _sources_for(*health), 1)
    assert sec["state"] == "partial"
    assert sec["failed"] == ["steam"]


def test_p_disabled_section_reports_disabled_not_empty(
    env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """enable_deals=False must read as 'switched off', never as 'nothing found'."""
    sec = webapp.section_state("deals", _sources_for(), 0)
    assert sec["state"] == "disabled"
    assert "ENABLE_DEALS" in sec["detail"]

    monkeypatch.setattr(settings, "enable_deals", True)
    assert webapp.section_state("deals", _sources_for(), 0)["state"] == "no_data"


def test_p_state_payload_exposes_all_section_states(env: Path, client: TestClient) -> None:
    sections = client.get("/api/state").json()["sections"]
    assert set(sections) == set(webapp.SECTION_SOURCES)
    assert sections["giveaways"]["state"] == "no_data"


def test_p_page_defines_copy_for_each_empty_state(env: Path, client: TestClient) -> None:
    """The page must carry distinct wording for each state, not one generic line."""
    page = client.get("/").text
    for state in ("no_data", "zero_results", "failed", "partial", "disabled"):
        assert f"{state}:" in page
    assert "have not been collected yet" in page
    assert "found nothing here" in page
    assert "failed on their last attempt" in page


# --------------------------------------------------------------------------
# Q — successful data reaches the overview
# --------------------------------------------------------------------------


def test_q_collected_data_appears_in_the_overview(
    env: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_SOURCES", {"epic": _Spy([_event("Overview Game")])})

    empty = client.get("/api/state").json()
    assert empty["collection"]["has_ever_run"] is False
    assert empty["counts"]["current_giveaways"] == 0

    assert client.post("/api/run").status_code == 200

    state = client.get("/api/state").json()
    assert state["collection"]["has_ever_run"] is True
    assert state["collection"]["last_success_at"] is not None
    assert state["counts"]["current_giveaways"] == 1
    assert state["sections"]["giveaways"]["state"] == "ok"
    assert any(g["title"] == "Overview Game" for g in state["giveaways"])


def test_q_run_history_is_surfaced_after_a_run(
    env: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert client.get("/api/runs").json()["runs"] == []
    monkeypatch.setattr(cli, "_SOURCES", {"epic": _Spy([_event()])})
    assert client.post("/api/run").status_code == 200

    runs = client.get("/api/runs").json()["runs"]
    assert len(runs) == 1
    assert runs[0]["new"] == 1
    assert runs[0]["generated_at"]


# --------------------------------------------------------------------------
# R — a duplicate / concurrent run is refused, not queued
# --------------------------------------------------------------------------


def test_r_second_request_is_refused_while_one_is_in_flight(
    env: Path, client: TestClient
) -> None:
    webapp._run_lock.acquire()
    try:
        resp = client.post("/api/run")
        assert resp.status_code == 409
        assert resp.json()["busy"] is True
    finally:
        webapp._run_lock.release()


def test_r_run_held_by_another_process_is_refused(
    env: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dashboard honours the same cross-process lock the CLI takes.

    A scheduled `newsroom run` holding the lock must block the button too —
    that is the whole point of reusing newsroom.run_lock instead of inventing
    a GUI-only one.
    """
    spy = _Spy([_event()])
    monkeypatch.setattr(cli, "_SOURCES", {"epic": spy})

    lock_path = settings.database_path.parent / "newsroom.lock"
    with run_lock.acquire(lock_path):
        resp = client.post("/api/run")

    assert resp.status_code == 409
    assert resp.json()["busy"] is True
    assert spy.calls == 0


def test_r_lock_is_released_so_the_next_run_succeeds(
    env: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = _Spy([_event()])
    monkeypatch.setattr(cli, "_SOURCES", {"epic": spy})
    assert client.post("/api/run").status_code == 200
    assert client.post("/api/run").status_code == 200
    assert spy.calls == 2


# --------------------------------------------------------------------------
# Registry / scheduler surface
# --------------------------------------------------------------------------


def test_registry_reports_unwired_modules_without_offering_to_run_them(env: Path) -> None:
    by_name = {s.name: s for s in cli.source_registry()}
    for name in ("prime_gaming", "amazon_luna", "apple_arcade"):
        assert by_name[name].wired is False
        assert by_name[name].runnable is False
        assert name not in cli.runnable_source_names()


def test_scheduler_endpoint_is_read_only(env: Path, client: TestClient) -> None:
    """The console reports scheduler state; it never registers or changes it."""
    payload = client.get("/api/scheduler").json()
    assert set(payload) >= {"supported", "task", "known", "state"}
    # Nothing in this module may write to the scheduler.
    source = Path(webapp.__file__).read_text(encoding="utf-8")
    forbidden = ("schtasks /create", "/change", "Register-ScheduledTask", "Enable-ScheduledTask")
    for token in forbidden:
        assert token not in source
