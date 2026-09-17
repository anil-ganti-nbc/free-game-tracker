"""The local web dashboard (``newsroom serve``).

A FastAPI app that turns the data we already collect into an operator console:
what was found, whether the sources are healthy, when they last ran, and an
explicit control to run them again. It is purely a read/trigger layer — no new
data model, no business logic, no second copy of the collectors. Everything
comes from the database, the reports directory, and the existing pipeline in
``newsroom.cli``.

Two invariants this module exists to uphold:

* **Loading the page never collects anything.** Every ``GET`` is a pure read of
  already-stored state. Collection starts only from an explicit ``POST
  /api/run``, i.e. only when an operator presses the button.
* **Mutation stays behind the existing gate.** ``/api/run`` requires both the
  injected ``phase0_mutation_authorizer`` (installed only by the loopback-bound
  ``newsroom serve``) and a loopback client address.

Kept deliberately dependency-light: one server module, a few JSON endpoints,
and a single self-contained HTML page (no framework, no build step).
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from newsroom import cli, run_lock
from newsroom.cli import (
    BREAKOUT_SOURCE,
    DEALS_SOURCE,
    _stale_sources,
    run_pipeline,
    runnable_source_names,
    source_registry,
)
from newsroom.config import settings
from newsroom.database import (
    SourceHealth,
    load_all_events,
    load_deals,
    load_new_releases,
    load_source_health,
)
from newsroom.models import NewRelease, NewsEvent, SteamDeal

logger = logging.getLogger(__name__)

app = FastAPI(title="Newsroom", docs_url=None, redoc_url=None)

# In-process guard. The cross-process guard is newsroom.run_lock, acquired
# inside the run itself; this one only avoids two browser tabs racing.
_run_lock = threading.Lock()

#: Which collection units feed which part of the page. Used to answer, per
#: section, "is this empty because nothing ran, because nothing was found, or
#: because the fetch failed?" — three situations a bare empty table conflates.
SECTION_SOURCES: dict[str, list[str]] = {
    "giveaways": ["epic", "steam", "gog", "gamerpower"],
    "subscriptions": ["playstation_plus", "xbox_game_pass", "geforce_now"],
    "breakouts": [BREAKOUT_SOURCE],
    "deals": [DEALS_SOURCE],
    "upcoming": ["epic"],
}

#: Live state of the operator-triggered run. Purely in-memory and intentionally
#: so: a run's durable record is the report file it writes plus the
#: source_health rows it updates. This only lets the page say "RUNNING" while
#: one is in flight and echo the outcome of the last one.
_RUN_STATE: dict[str, Any] = {
    "status": "idle",
    "scope": None,
    "started_at": None,
    "finished_at": None,
    "outcome": None,
    "message": None,
    "summary": None,
}


class RunRequest(BaseModel):
    """Optional body for ``POST /api/run``. Absent body means "run everything"."""

    sources: list[str] | None = None


# --------------------------------------------------------------------------
# Serialization
# --------------------------------------------------------------------------


def _display_props(event: NewsEvent) -> dict[str, Any]:
    from newsroom.models import Category

    is_sub = event.category == Category.SUBSCRIPTION

    if is_sub:
        start = event.available_from
        end = event.available_until or event.claim_deadline
        service_name = event.service or "Subscription"
        ev_type = event.event_type.value.replace("_", " ") if event.event_type else ""
        label = f"{service_name} {ev_type}".strip()
    else:
        start = event.promotion_start
        end = event.promotion_end
        label = "Giveaway"

    return {
        "display_start": start.isoformat() if start else "",
        "display_end": end.isoformat() if end else "",
        "bucket": "expired" if event.is_expired() else "current",
        "label": label,
        "is_subscription": is_sub,
        "category": event.category.value,
    }


def _serialize_event(event: NewsEvent) -> dict[str, Any]:
    d = {
        "source": event.source.value,
        "title": event.title,
        "url": event.url,
        "promotion_type": event.promotion_type.value,
        "original_price": event.original_price,
        "current_price": event.current_price,
        "promotion_end": event.promotion_end.isoformat() if event.promotion_end else None,
        "confidence": event.confidence.score,
        "developer": event.developer,
        "publisher": event.publisher,
        "event_type": event.event_type.value if event.event_type else None,
        "access_model": event.access_model.value if event.access_model else None,
        "ownership_model": event.ownership_model.value if event.ownership_model else None,
        "service": event.service,
        "tiers": event.tiers,
        "platforms": event.platforms,
        "regions": event.regions,
        "storefronts": event.storefronts,
        "available_from": event.available_from.isoformat() if event.available_from else None,
        "available_until": event.available_until.isoformat() if event.available_until else None,
        "claim_deadline": event.claim_deadline.isoformat() if event.claim_deadline else None,
        "day_one": event.day_one,
    }
    d.update(_display_props(event))
    return d


def _serialize_health(health: SourceHealth, stale: bool) -> dict[str, Any]:
    return {
        "source": health.source,
        "status": health.last_status,
        "stale": stale,
        "last_success_at": (health.last_success_at.isoformat() if health.last_success_at else None),
        "last_attempt_at": health.last_attempt_at.isoformat(),
        "count": health.last_count,
        "error": health.last_error,
    }


def _serialize_release(release: NewRelease, now: datetime) -> dict[str, Any]:
    return {
        "appid": release.appid,
        "name": release.name,
        "url": release.url,
        "release_date": release.release_date.date().isoformat(),
        "days_since": max((now - release.release_date).days, 0),
        "review_desc": release.review_desc,
        "total_reviews": release.total_reviews,
        "positive_pct": release.positive_pct,
    }


def _serialize_deal(deal: SteamDeal) -> dict[str, Any]:
    return {
        "appid": deal.appid,
        "name": deal.name,
        "url": deal.url,
        "discount_percent": deal.discount_percent,
        "original_price": deal.original_price,
        "final_price": deal.final_price,
        "review_desc": deal.review_desc,
        "total_reviews": deal.total_reviews,
        "positive_pct": deal.positive_pct,
        "discount_end": deal.discount_end.date().isoformat() if deal.discount_end else None,
    }


def _sort_key_event(event: NewsEvent, now: datetime) -> tuple[int, float, str, str]:
    """Sort key for dashboard display.

    1. bucket: 0 for current/upcoming, 1 for historical/expired
    2. newest availability date (descending, so negated timestamp)
    3. source as tie-breaker
    4. title as tie-breaker
    """
    is_expired = event.is_expired()
    bucket = 1 if is_expired else 0

    ts = 0.0
    if event.available_from:
        dt = event.available_from
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        ts = dt.timestamp()

    return (bucket, -ts, event.source.value, (event.title or "").lower())


# --------------------------------------------------------------------------
# Source view: the registry joined to recorded health
# --------------------------------------------------------------------------


def build_sources(health: list[SourceHealth], stale: set[str]) -> list[dict[str, Any]]:
    """Join every known collection unit to whatever health we have recorded.

    A unit with no ``source_health`` row has never been attempted, which is a
    different fact from "attempted and returned nothing" and a different fact
    again from "attempted and failed". All three are represented distinctly
    here so the page never has to guess.

    Zero items is never treated as unhealthy: ``last_status`` comes straight
    from whether the fetch raised.
    """
    by_name = {h.source: h for h in health}
    rows: list[dict[str, Any]] = []
    for spec in source_registry():
        h = by_name.get(spec.name)
        if not spec.wired:
            status = "not_wired"
        elif not spec.enabled:
            status = "disabled"
        elif h is None:
            status = "never_run"
        elif h.last_status != "ok":
            status = "error"
        elif spec.name in stale:
            status = "stale"
        else:
            status = "ok"
        rows.append(
            {
                "name": spec.name,
                "label": spec.label,
                "kind": spec.kind,
                "scope": spec.scope,
                "wired": spec.wired,
                "enabled": spec.enabled,
                "runnable": spec.runnable,
                "disabled_reason": spec.disabled_reason,
                "status": status,
                "last_attempt_at": h.last_attempt_at.isoformat() if h else None,
                "last_success_at": (h.last_success_at.isoformat() if h and h.last_success_at else None),
                "items": h.last_count if h else None,
                "error": h.last_error if h else None,
            }
        )
    return rows


def section_state(section: str, sources: list[dict[str, Any]], count: int) -> dict[str, Any]:
    """Classify why a section looks the way it does.

    Returns one of:
      ``no_data``      nothing has ever been collected for this section
      ``failed``       every source that feeds it failed its last attempt
      ``partial``      some of its sources failed; what's shown is incomplete
      ``zero_results`` a successful collection genuinely found nothing
      ``disabled``     every source that feeds it is switched off or unwired
      ``ok``           has data from a successful collection
    """
    names = SECTION_SOURCES.get(section, [])
    feeding = [s for s in sources if s["name"] in names]
    live = [s for s in feeding if s["runnable"]]
    if feeding and not live:
        reasons = sorted({s["disabled_reason"] or "unavailable" for s in feeding})
        return {"state": "disabled", "count": count, "sources": names, "detail": "; ".join(reasons)}

    attempted = [s for s in live if s["status"] != "never_run"]
    failed = [s for s in attempted if s["status"] == "error"]

    if not attempted:
        state = "no_data"
    elif len(failed) == len(attempted):
        state = "failed"
    elif failed:
        state = "partial"
    elif count == 0:
        state = "zero_results"
    else:
        state = "ok"

    detail = ""
    if failed:
        detail = "; ".join(f"{s['name']}: {s['error'] or 'failed'}" for s in failed)
    return {
        "state": state,
        "count": count,
        "sources": names,
        "failed": [s["name"] for s in failed],
        "detail": detail,
    }


# --------------------------------------------------------------------------
# Run history — read back from the reports the pipeline already writes
# --------------------------------------------------------------------------


def load_run_history(limit: int = 25) -> list[dict[str, Any]]:
    """Summarize recent runs from the per-run report JSON already on disk.

    ``write_reports`` writes ``report-<stamp>.json`` for every run, each with a
    ``generated_at`` and a ``summary`` block. That is the run log this app
    already keeps, so it is what we surface — no new table, no new subsystem.
    Retention therefore follows ``NEWSROOM_REPORT_RETENTION_DAYS``.
    """
    reports_dir = settings.reports_dir
    if not reports_dir.exists():
        return []
    try:
        paths = sorted(reports_dir.glob("report-*.json"), reverse=True)[:limit]
    except OSError:
        return []
    runs: list[dict[str, Any]] = []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("Unreadable run report skipped: %s", path)
            continue
        counts = data.get("summary") or {}
        runs.append(
            {
                "generated_at": data.get("generated_at"),
                "file": path.name,
                "new": counts.get("new"),
                "ending_soon": counts.get("ending_soon"),
                "expired": counts.get("expired"),
                "upcoming": counts.get("upcoming"),
                "suppressed": counts.get("suppressed"),
            }
        )
    return runs


# --------------------------------------------------------------------------
# Scheduler visibility (read-only, best effort, never mutates)
# --------------------------------------------------------------------------

SCHEDULED_TASK_NAME = "Newsroom Free Game Tracker"
_scheduler_cache: dict[str, Any] = {"at": 0.0, "value": None}
_SCHEDULER_TTL_SECONDS = 60.0


def read_scheduler() -> dict[str, Any]:
    """Report the Windows scheduled task's state without ever changing it.

    Strictly a query (``schtasks /query``). This dashboard never registers,
    enables, disables, or re-times a scheduled task; it only tells the operator
    what the OS currently says, because "nothing has run" is very often a
    scheduler fact rather than an application fact.
    """
    now = time.monotonic()
    cached = _scheduler_cache["value"]
    if cached is not None and now - float(_scheduler_cache["at"]) < _SCHEDULER_TTL_SECONDS:
        return dict(cached)

    result: dict[str, Any] = {
        "supported": sys.platform == "win32",
        "task": SCHEDULED_TASK_NAME,
        "known": False,
        "state": None,
        "next_run": None,
        "last_run": None,
        "last_result": None,
        "note": None,
    }
    if not result["supported"]:
        result["note"] = "Scheduling is external on this platform (cron/systemd timer)."
    else:
        try:
            proc = subprocess.run(
                ["schtasks", "/query", "/tn", SCHEDULED_TASK_NAME, "/fo", "LIST", "/v"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if proc.returncode == 0:
                fields = {}
                for line in proc.stdout.splitlines():
                    if ":" in line:
                        key, _, value = line.partition(":")
                        fields[key.strip().lower()] = value.strip()
                result["known"] = True
                result["state"] = fields.get("scheduled task state") or fields.get("status")
                result["next_run"] = fields.get("next run time")
                result["last_run"] = fields.get("last run time")
                result["last_result"] = fields.get("last result")
            else:
                result["note"] = "No scheduled task registered for this collector."
        except (OSError, subprocess.SubprocessError) as exc:
            result["note"] = f"Could not query the scheduler: {exc}"

    _scheduler_cache["at"] = now
    _scheduler_cache["value"] = dict(result)
    return result


# --------------------------------------------------------------------------
# State assembly
# --------------------------------------------------------------------------


def run_controls_enabled() -> bool:
    """Whether this process is allowed to start a collection at all."""
    authorizer = getattr(app.state, "phase0_mutation_authorizer", None)
    return bool(authorizer is not None and authorizer())


def get_state() -> dict[str, Any]:
    """Assemble the dashboard's data. A pure read — it never collects anything."""
    now = datetime.now(UTC)
    events = sorted(load_all_events(), key=lambda e: _sort_key_event(e, now))
    health = sorted(load_source_health(), key=lambda h: h.source)
    stale = set(_stale_sources(health, settings.source_stale_hours))
    breakouts = sorted(load_new_releases(), key=lambda r: r.release_date, reverse=True)
    deals = sorted(load_deals(), key=lambda d: d.discount_percent, reverse=True)

    upcoming: list[dict[str, Any]] = []
    generated_at: str | None = None
    latest = settings.reports_dir / "latest.json"
    if latest.exists():
        try:
            data = json.loads(latest.read_text(encoding="utf-8"))
            upcoming = data.get("upcoming", [])
            generated_at = data.get("generated_at")
        except (OSError, ValueError):
            pass

    sources = build_sources(health, stale)
    giveaways = [e for e in events if e.category.value != "subscription"]
    subscriptions = [e for e in events if e.category.value == "subscription"]
    current_giveaways = [e for e in giveaways if not e.is_expired()]
    current_subscriptions = [e for e in subscriptions if not e.is_expired()]

    last_attempt = max((h.last_attempt_at for h in health), default=None)
    last_success = max((h.last_success_at for h in health if h.last_success_at), default=None)
    failing = [s for s in sources if s["status"] == "error"]

    return {
        "generated_at": generated_at,
        "counts": {
            "giveaways": len(events),
            "sources": len(health),
            "upcoming": len(upcoming),
            "stale": len(stale),
            "breakouts": len(breakouts),
            "deals": len(deals),
            "current_giveaways": len(current_giveaways),
            "current_subscriptions": len(current_subscriptions),
            "failing": len(failing),
            "runnable": len(runnable_source_names()),
        },
        "collection": {
            "has_ever_run": bool(health),
            "last_attempt_at": last_attempt.isoformat() if last_attempt else None,
            "last_success_at": last_success.isoformat() if last_success else None,
            "stale_hours": settings.source_stale_hours,
            "run_controls_enabled": run_controls_enabled(),
            "database_path": str(settings.database_path),
            "run": dict(_RUN_STATE),
        },
        "sections": {
            "giveaways": section_state("giveaways", sources, len(current_giveaways)),
            "subscriptions": section_state("subscriptions", sources, len(current_subscriptions)),
            "breakouts": section_state("breakouts", sources, len(breakouts)),
            "deals": section_state("deals", sources, len(deals)),
            "upcoming": section_state("upcoming", sources, len(upcoming)),
        },
        "sources": sources,
        "giveaways": [_serialize_event(e) for e in events],
        "health": [_serialize_health(h, h.source in stale) for h in health],
        "upcoming": upcoming,
        "breakouts": [_serialize_release(r, now) for r in breakouts],
        "deals": [_serialize_deal(d) for d in deals],
    }


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------


@app.get("/api/state")
def api_state() -> dict[str, Any]:
    """Return the current dashboard state as JSON. Read-only by construction."""
    return get_state()


@app.get("/api/runs")
def api_runs() -> dict[str, Any]:
    """Return recent runs, reconstructed from the report files on disk."""
    return {"runs": load_run_history()}


@app.get("/api/scheduler")
def api_scheduler() -> dict[str, Any]:
    """Report the OS scheduler's view of this collector. Never modifies it."""
    return read_scheduler()


def _client_is_loopback(request: Request) -> bool:
    """Whether the request came from this machine.

    A second, independent check on top of the authorizer gate: even if a future
    change hosted this app somewhere less careful, the mutation endpoint still
    refuses a non-local caller.
    """
    import ipaddress

    client = request.client
    if client is None:
        return False
    try:
        return ipaddress.ip_address(client.host).is_loopback
    except ValueError:
        return client.host.lower() in {"localhost", "testclient"}


def _plan_run(requested: list[str] | None) -> dict[str, Any]:
    """Translate requested unit names into arguments for the canonical pipeline.

    Only units the registry reports as runnable may be named. A disabled or
    unwired source cannot be started from here — asking for one is an error,
    not an implicit enablement.
    """
    runnable = runnable_source_names()
    if not requested:
        names = list(runnable)
    else:
        unknown = [n for n in requested if n not in runnable]
        if unknown:
            raise ValueError(
                f"not runnable: {', '.join(sorted(unknown))}. "
                f"Runnable units are: {', '.join(runnable)}."
            )
        names = list(dict.fromkeys(requested))

    # Read through the module so a test (or a future dynamic registration) that
    # rebinds cli._SOURCES is honoured rather than shadowed by an import-time copy.
    event_sources = [
        n
        for n in names
        if n in cli._SOURCES or n in cli.DISCOVERY_SOURCES or n in cli.INTEL_SOURCES
    ]
    return {
        "scope": names,
        "selected": event_sources or None,
        "include_sources": bool(event_sources),
        "include_breakouts": BREAKOUT_SOURCE in names,
        "include_deals": DEALS_SOURCE in names,
    }


@app.post("/api/run")
def api_run(request: Request, body: RunRequest | None = None) -> JSONResponse:
    """Start one collection cycle. This is the only way collection ever starts.

    Refuses rather than queues when a run is already active — including a run
    started outside this process (the hourly task, or the CLI), which is why we
    take ``newsroom.run_lock`` on the same lock file ``newsroom run`` uses
    rather than inventing a dashboard-only lock.
    """
    if not run_controls_enabled():
        return JSONResponse(
            {"ok": False, "error": "Phase 0 dashboard is read-only; authenticated profile required."},
            status_code=403,
        )
    if not _client_is_loopback(request):
        return JSONResponse(
            {"ok": False, "error": "Run controls are available to local clients only."},
            status_code=403,
        )

    try:
        plan = _plan_run(body.sources if body else None)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    if not _run_lock.acquire(blocking=False):
        return JSONResponse(
            {"ok": False, "error": "A run is already in progress.", "busy": True}, status_code=409
        )
    try:
        started = datetime.now(UTC)
        lock_path = settings.database_path.parent / "newsroom.lock"
        try:
            with run_lock.acquire(lock_path):
                _RUN_STATE.update(
                    status="running",
                    scope=plan["scope"],
                    started_at=started.isoformat(),
                    finished_at=None,
                    outcome=None,
                    message=None,
                    summary=None,
                )
                try:
                    summary = run_pipeline(
                        selected=plan["selected"],
                        include_sources=plan["include_sources"],
                        include_breakouts=plan["include_breakouts"],
                        include_deals=plan["include_deals"],
                    )
                except Exception as exc:  # noqa: BLE001 - reported, never swallowed
                    logger.exception("Operator-triggered run failed")
                    _RUN_STATE.update(
                        status="idle",
                        finished_at=datetime.now(UTC).isoformat(),
                        outcome="error",
                        message=f"{type(exc).__name__}: {exc}",
                    )
                    return JSONResponse(
                        {"ok": False, "error": f"Run failed: {type(exc).__name__}: {exc}"},
                        status_code=500,
                    )
                _RUN_STATE.update(
                    status="idle",
                    finished_at=datetime.now(UTC).isoformat(),
                    outcome="ok",
                    message=None,
                    summary=summary,
                )
                return JSONResponse({"ok": True, "summary": summary})
        except run_lock.RunLockError as exc:
            return JSONResponse(
                {"ok": False, "error": str(exc), "busy": True},
                status_code=409,
            )
    finally:
        _run_lock.release()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """Serve the single-page dashboard. Renders stored state only."""
    return _PAGE


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Newsroom — Free Game Watch</title>
<style>
:root{
  --bg:#0d1117; --surface:#151b23; --surface-2:#1b222c; --surface-3:#222b37;
  --line:#2a3441; --line-strong:#3a4757;
  --text:#e6edf3; --text-dim:#adbac7; --muted:#7d8b9a;
  --accent:#e3a008; --accent-soft:#2e2410;
  --ok:#3fb950; --ok-soft:#12261a;
  --warn:#d29922; --warn-soft:#2b2213;
  --bad:#f85149; --bad-soft:#2d1618;
  --info:#58a6ff; --info-soft:#12233b;
  --idle:#8b949e; --idle-soft:#1e242c;
  --s1:4px; --s2:8px; --s3:12px; --s4:16px; --s5:24px; --s6:32px;
  --r1:4px; --r2:6px; --r3:10px;
  --font:ui-sans-serif,-apple-system,Segoe UI,Roboto,Helvetica Neue,Arial,sans-serif;
  --mono:ui-monospace,Cascadia Mono,SFMono-Regular,Menlo,Consolas,monospace;
  --fs-page:20px; --fs-section:14px; --fs-body:13px; --fs-meta:12px; --fs-label:11px; --fs-kpi:27px;
  --maxw:1680px; --rail:212px;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:var(--bg);color:var(--text);
  font-family:var(--font);font-size:var(--fs-body);line-height:1.45;-webkit-font-smoothing:antialiased}
a{color:var(--accent);text-decoration:none} a:hover{text-decoration:underline}

.app{min-height:100vh;display:flex;flex-direction:column}
.topbar{display:flex;align-items:center;gap:var(--s4);padding:0 var(--s5);height:52px;
  background:var(--surface);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:40}
.brand{display:flex;align-items:center;gap:var(--s2);min-width:0}
.brand-mark{width:22px;height:22px;border-radius:var(--r2);background:var(--accent);color:#1c1403;
  display:inline-flex;align-items:center;justify-content:center;font-weight:800;font-size:12px;flex:none}
.brand-name{font-size:15px;font-weight:700;letter-spacing:-.01em;white-space:nowrap}
.brand-suite{font-size:var(--fs-label);color:var(--muted);text-transform:uppercase;
  letter-spacing:.09em;white-space:nowrap}
.topbar-meta{margin-left:auto;display:flex;align-items:center;gap:var(--s3);
  font-size:var(--fs-meta);color:var(--muted);white-space:nowrap}

.body{display:flex;flex:1;min-height:0}
.rail{width:var(--rail);flex:none;background:var(--surface);border-right:1px solid var(--line);
  padding:var(--s4) var(--s3);display:flex;flex-direction:column;gap:2px}
.rail-group{font-size:var(--fs-label);color:var(--muted);text-transform:uppercase;
  letter-spacing:.09em;margin:var(--s4) var(--s2) var(--s1)}
.rail-group.first{margin-top:0}
.nav{display:flex;align-items:center;gap:var(--s2);padding:7px var(--s3);border-radius:var(--r2);
  color:var(--text-dim);font-size:var(--fs-body);font-weight:500}
.nav:hover{background:var(--surface-2);color:var(--text);text-decoration:none}
.nav .count{margin-left:auto;font-size:var(--fs-label);color:var(--muted)}
.main{flex:1;min-width:0;padding:var(--s5)}
.wrap{max-width:var(--maxw);margin:0 auto}
.page-head{margin-bottom:var(--s5)}
.page-title{font-size:var(--fs-page);font-weight:700;margin:0;letter-spacing:-.02em}
.page-sub{color:var(--muted);font-size:var(--fs-meta);margin:var(--s1) 0 0}
.foot{border-top:1px solid var(--line);padding:var(--s3) var(--s5);color:var(--muted);
  font-size:var(--fs-meta);display:flex;gap:var(--s4);flex-wrap:wrap}

.panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--r3);
  margin-bottom:var(--s4);scroll-margin-top:64px}
.panel-head{display:flex;align-items:center;gap:var(--s3);padding:var(--s3) var(--s4);
  border-bottom:1px solid var(--line);flex-wrap:wrap}
.panel-title{font-size:var(--fs-section);font-weight:650;margin:0}
.panel-sub{font-size:var(--fs-meta);color:var(--muted);margin-left:auto}
.panel-body{padding:var(--s4)}
.panel-body.flush{padding:0}

.kpis{display:grid;gap:var(--s3);margin-bottom:var(--s4);
  grid-template-columns:repeat(auto-fit,minmax(178px,1fr))}
.kpi{background:var(--surface);border:1px solid var(--line);border-radius:var(--r3);
  padding:var(--s3) var(--s4)}
.kpi-label{font-size:var(--fs-label);color:var(--muted);text-transform:uppercase;
  letter-spacing:.07em;font-weight:600}
.kpi-value{font-size:var(--fs-kpi);font-weight:700;line-height:1.15;margin-top:2px;letter-spacing:-.02em}
.kpi-value.sm{font-size:16px}
.kpi-note{font-size:var(--fs-meta);color:var(--muted);margin-top:2px}
.kpi.is-ok{border-color:#1e4429} .kpi.is-warn{border-color:#4a3a15} .kpi.is-bad{border-color:#4d2225}

.badge{display:inline-flex;align-items:center;gap:5px;padding:2px var(--s2);border-radius:999px;
  font-size:var(--fs-label);font-weight:650;letter-spacing:.03em;background:var(--idle-soft);
  color:var(--idle);border:1px solid transparent;white-space:nowrap}
.badge::before{content:"\\25CF";font-size:8px;line-height:1}
.badge.ok{background:var(--ok-soft);color:var(--ok);border-color:#1e4429}
.badge.warn{background:var(--warn-soft);color:var(--warn);border-color:#4a3a15}
.badge.bad{background:var(--bad-soft);color:var(--bad);border-color:#4d2225}
.badge.info{background:var(--info-soft);color:var(--info);border-color:#1d3a5c}
.badge.accent{background:var(--accent-soft);color:var(--accent)}
.badge.plain::before{content:none}

.tablewrap{overflow-x:auto}
table.t{width:100%;border-collapse:collapse;font-size:var(--fs-body)}
table.t thead th{background:var(--surface-2);color:var(--muted);font-size:var(--fs-label);
  font-weight:650;text-transform:uppercase;letter-spacing:.06em;text-align:left;
  padding:var(--s2) var(--s3);border-bottom:1px solid var(--line)}
table.t tbody td{padding:9px var(--s3);border-bottom:1px solid var(--line);vertical-align:middle}
table.t tbody tr:last-child td{border-bottom:none}
table.t tbody tr:hover{background:var(--surface-2)}
table.t td.num,table.t th.num{text-align:right;font-variant-numeric:tabular-nums}
table.t td.dim{color:var(--muted)}
table.t td.wrap-any{white-space:normal;word-break:break-word}
.mono{font-family:var(--mono);font-size:var(--fs-meta)}

.empty{padding:var(--s6) var(--s4);text-align:center;color:var(--muted)}
.empty-title{color:var(--text-dim);font-weight:600;margin-bottom:var(--s1)}
.empty-hint{font-size:var(--fs-meta);max-width:62ch;margin:0 auto}
.empty .badge{margin-bottom:var(--s3)}

.notice{display:flex;gap:var(--s3);align-items:flex-start;padding:var(--s3) var(--s4);
  border-radius:var(--r3);border:1px solid var(--line);background:var(--surface-2);
  margin-bottom:var(--s4);font-size:var(--fs-body)}
.notice .notice-title{font-weight:650}
.notice .notice-text{color:var(--text-dim);font-size:var(--fs-meta);margin-top:2px}
.notice.warn{border-color:#4a3a15;background:var(--warn-soft)}
.notice.bad{border-color:#4d2225;background:var(--bad-soft)}
.notice.info{border-color:#1d3a5c;background:var(--info-soft)}
.notice.accent{border-color:#5a4712;background:var(--accent-soft)}

.btn{display:inline-flex;align-items:center;gap:6px;padding:6px var(--s3);border-radius:var(--r2);
  font-size:var(--fs-body);font-weight:600;font-family:inherit;border:1px solid var(--line-strong);
  background:var(--surface-2);color:var(--text);cursor:pointer;line-height:1.4}
.btn:hover:not(:disabled){background:var(--surface-3)}
.btn:disabled{opacity:.45;cursor:not-allowed}
.btn.primary{background:var(--accent);border-color:var(--accent);color:#1c1403}
.btn.primary:hover:not(:disabled){filter:brightness(1.08)}
.btn.sm{padding:3px var(--s2);font-size:var(--fs-label)}

input[type=range]{-webkit-appearance:none;appearance:none;width:130px;background:transparent;
  vertical-align:middle;margin:0 var(--s2)}
input[type=range]::-webkit-slider-runnable-track{height:4px;background:var(--line);border-radius:2px}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;height:14px;width:14px;
  border-radius:50%;background:var(--accent);margin-top:-5px;cursor:pointer}
input[type=range]::-moz-range-track{height:4px;background:var(--line);border-radius:2px}
input[type=range]::-moz-range-thumb{height:14px;width:14px;border-radius:50%;
  background:var(--accent);border:none;cursor:pointer}

.stack{display:flex;flex-direction:column;gap:2px}
.row{display:flex;align-items:center;gap:var(--s2);flex-wrap:wrap}
.right{margin-left:auto}
.muted{color:var(--muted)}
small{display:block;color:var(--muted);font-size:var(--fs-label);font-weight:400}

@media(max-width:1000px){
  .body{flex-direction:column}
  .rail{width:auto;flex-direction:row;overflow-x:auto;border-right:none;
    border-bottom:1px solid var(--line);padding:var(--s2) var(--s3)}
  .rail-group{display:none}
  .nav{white-space:nowrap}
  .main{padding:var(--s4)}
}
</style>
</head>
<body>
<div class="app">
<div class="topbar">
  <div class="brand">
    <span class="brand-mark">N</span>
    <span class="brand-name">Newsroom</span>
    <span class="brand-suite">Free Game Watch</span>
  </div>
  <div class="topbar-meta">
    <span id="tb-run"></span>
    <span id="tb-last"></span>
  </div>
</div>
<div class="body">
  <nav class="rail">
    <div class="rail-group first">Operations</div>
    <a class="nav" href="#overview">Overview</a>
    <a class="nav" href="#sources">Sources &amp; run control<span class="count" id="n-src"></span></a>
    <a class="nav" href="#history">Run history<span class="count" id="n-hist"></span></a>
    <div class="rail-group">Desks</div>
    <a class="nav" href="#giveaways">Free giveaways<span class="count" id="n-give"></span></a>
    <a class="nav" href="#subscriptions">Subscription catalog<span class="count" id="n-subs"></span></a>
    <a class="nav" href="#breakouts">Breakout releases<span class="count" id="n-break"></span></a>
    <a class="nav" href="#deals">Steam deals<span class="count" id="n-deals"></span></a>
    <a class="nav" href="/discovery">Discovery evidence</a>
    <a class="nav" href="#upcoming">Upcoming<span class="count" id="n-up"></span></a>
  </nav>
  <main class="main"><div class="wrap">

    <div class="page-head">
      <h1 class="page-title">Operations overview</h1>
      <p class="page-sub" id="subtitle">Loading…</p>
    </div>

    <div id="banners"></div>
    <div id="banners-sched"></div>

    <section id="overview">
      <div class="kpis" id="kpis"></div>
    </section>

    <section class="panel" id="sources">
      <div class="panel-head">
        <h2 class="panel-title">Sources &amp; run control</h2>
        <div class="row right">
          <span id="run-msg" class="muted" style="font-size:var(--fs-meta)"></span>
          <button class="btn primary" id="run-all">Run all safe sources</button>
        </div>
      </div>
      <div class="panel-body flush"><div class="tablewrap" id="sources-table"></div></div>
    </section>

    <section class="panel" id="giveaways">
      <div class="panel-head"><h2 class="panel-title">Current free giveaways</h2>
        <span class="panel-sub" id="giveaways-sub"></span></div>
      <div class="panel-body flush" id="giveaways-body"></div>
    </section>

    <section class="panel" id="subscriptions">
      <div class="panel-head"><h2 class="panel-title">Subscription catalog &amp; claims</h2>
        <span class="panel-sub" id="subscriptions-sub"></span></div>
      <div class="panel-body flush" id="subscriptions-body"></div>
    </section>

    <section class="panel" id="breakouts">
      <div class="panel-head"><h2 class="panel-title">Breakout new releases</h2>
        <span class="panel-sub">within <span id="dayval">14</span> days
          <input id="days" type="range" min="1" max="14" value="14" oninput="renderBreakouts()"></span>
      </div>
      <div class="panel-body flush" id="breakouts-body"></div>
    </section>

    <section class="panel" id="deals">
      <div class="panel-head"><h2 class="panel-title">Steam deals</h2>
        <span class="panel-sub" id="deals-sub"></span></div>
      <div class="panel-body flush" id="deals-body"></div>
    </section>

    <section class="panel" id="upcoming">
      <div class="panel-head"><h2 class="panel-title">Upcoming (heads-up)</h2>
        <span class="panel-sub" id="upcoming-sub"></span></div>
      <div class="panel-body flush" id="upcoming-body"></div>
    </section>

    <section class="panel" id="history">
      <div class="panel-head"><h2 class="panel-title">Run history</h2>
        <span class="panel-sub">Reconstructed from run reports on disk</span></div>
      <div class="panel-body flush" id="history-body"></div>
    </section>

  </div></main>
</div>
<div class="foot">
  <span id="foot-db"></span>
  <span id="foot-sched"></span>
  <span>Loopback-only operator console. Loading this page never starts collection.</span>
</div>
</div>
<script>
const $ = id => document.getElementById(id);
let STATE = null, RUNNING = false;

function esc(s){ const d=document.createElement("div"); d.textContent=(s===null||s===undefined)?"":s; return d.innerHTML; }
function money(v){ return (v===null||v===undefined)?"\\u2014":("$"+Number(v).toFixed(2)); }
function when(iso){ return iso ? new Date(iso).toLocaleString() : "never"; }
function ago(iso){
  if(!iso) return "never";
  const mins = Math.round((Date.now()-new Date(iso).getTime())/60000);
  if(mins < 1) return "just now";
  if(mins < 60) return mins+"m ago";
  const h = Math.round(mins/60);
  if(h < 48) return h+"h ago";
  return Math.round(h/24)+"d ago";
}

/* --- empty states: three genuinely different situations, never conflated --- */
const EMPTY = {
  no_data: {
    badge:["info","No data yet"],
    title:"These sources have not been collected yet",
    hint:"Nothing has ever been fetched for this desk. Use \\u201cRun all safe sources\\u201d above to populate it."
  },
  zero_results: {
    badge:["ok","Collected \\u2014 nothing found"],
    title:"The latest successful collection found nothing here",
    hint:"This is a healthy result, not a failure: the sources answered and had no qualifying items."
  },
  failed: {
    badge:["bad","Collection failed"],
    title:"The sources feeding this desk failed on their last attempt",
    hint:"What follows is the reported cause. Anything shown elsewhere may be stale."
  },
  partial: {
    badge:["warn","Partial collection"],
    title:"Some sources feeding this desk failed",
    hint:"What is shown is incomplete \\u2014 items from the failed sources are missing."
  },
  disabled: {
    badge:["plain","Disabled"],
    title:"This desk\\u2019s sources are switched off",
    hint:"Nothing is collected for it in the current configuration."
  }
};

function emptyBlock(sec){
  const e = EMPTY[sec.state] || EMPTY.no_data;
  const detail = sec.detail ? `<p class="empty-hint mono" style="margin-top:8px;color:var(--bad)">${esc(sec.detail)}</p>` : "";
  return `<div class="empty"><span class="badge ${e.badge[0]}">${esc(e.badge[1])}</span>
    <div class="empty-title">${e.title}</div>
    <p class="empty-hint">${e.hint}</p>${detail}</div>`;
}

/* A section renders its table when it has rows; otherwise it explains itself. */
function renderSection(bodyId, subId, sec, rows, tableHtml){
  const sub = $(subId);
  if(sub) sub.textContent = sec.state === "ok" ? `${rows} shown` : "";
  $(bodyId).innerHTML = rows ? tableHtml : emptyBlock(sec);
  if(rows && (sec.state === "partial" || sec.state === "failed")){
    $(bodyId).insertAdjacentHTML("afterbegin",
      `<div class="notice warn" style="margin:12px">
         <div><div class="notice-title">Incomplete \\u2014 ${esc(sec.failed.join(", "))} failed</div>
         <div class="notice-text mono">${esc(sec.detail)}</div></div></div>`);
  }
}

const SRC_BADGE = {
  ok:["ok","OK"], stale:["warn","Stale"], error:["bad","Failed"],
  never_run:["info","Never run"], disabled:["plain","Disabled"], not_wired:["plain","Not wired"]
};

function renderSources(){
  const s = STATE;
  const rows = s.sources.map(src => {
    const b = SRC_BADGE[src.status] || ["plain", src.status];
    const cause = src.status === "error" ? (src.error || "unknown error")
                : (src.disabled_reason || "");
    const action = src.runnable
      ? `<button class="btn sm" data-run="${esc(src.name)}" ${RUNNING?"disabled":""}>Run</button>`
      : `<span class="muted" style="font-size:var(--fs-label)">not runnable</span>`;
    return `<tr>
      <td><div class="stack"><span>${esc(src.label)}</span><small>${esc(src.name)} \\u00b7 ${esc(src.kind)}</small></div></td>
      <td><span class="badge ${b[0]}">${esc(b[1])}</span></td>
      <td class="dim">${esc(ago(src.last_attempt_at))}</td>
      <td class="dim">${esc(ago(src.last_success_at))}</td>
      <td class="num">${src.items===null||src.items===undefined ? "\\u2014" : src.items}</td>
      <td class="wrap-any dim mono">${esc(cause)}</td>
      <td class="wrap-any dim" style="max-width:34ch">${esc(src.scope)}</td>
      <td>${action}</td></tr>`;
  }).join("");
  $("sources-table").innerHTML = `<table class="t"><thead><tr>
    <th>Source</th><th>Status</th><th>Last run</th><th>Last success</th>
    <th class="num">Items</th><th>Error / cause</th><th>Scope</th><th>Run</th>
    </tr></thead><tbody>${rows}</tbody></table>`;
  document.querySelectorAll("[data-run]").forEach(b =>
    b.addEventListener("click", () => runNow([b.getAttribute("data-run")])));
}

function renderBreakouts(){
  if(!STATE) return;
  const days = Number($("days").value); $("dayval").textContent = days;
  const rows = STATE.breakouts.filter(b => b.days_since <= days);
  const sec = Object.assign({}, STATE.sections.breakouts);
  // Filtered to nothing by the slider is a UI choice, not a collection outcome.
  if(STATE.breakouts.length && !rows.length){
    $("breakouts-body").innerHTML =
      `<div class="empty"><div class="empty-title">No breakout releases within ${days} days</div>
       <p class="empty-hint">${STATE.breakouts.length} release(s) collected fall outside this window \\u2014 widen the slider.</p></div>`;
    return;
  }
  renderSection("breakouts-body", null, sec, rows.length, `<table class="t"><thead><tr>
    <th>Game</th><th>Reviews</th><th class="num">Count</th><th class="num">Positive</th>
    <th>Released</th><th class="num">Age</th></tr></thead><tbody>` +
    rows.map(b => `<tr>
      <td><a href="${esc(b.url)}" target="_blank" rel="noopener">${esc(b.name)}</a></td>
      <td class="dim">${esc(b.review_desc)}</td>
      <td class="num">${b.total_reviews.toLocaleString()}</td>
      <td class="num">${b.positive_pct}%</td>
      <td class="dim">${esc(b.release_date)}</td>
      <td class="num">${b.days_since}d</td></tr>`).join("") + `</tbody></table>`);
}

function renderKpis(){
  const s = STATE, c = s.counts, col = s.collection;
  const failing = c.failing, stale = c.stale;
  const healthClass = failing ? "is-bad" : (stale ? "is-warn" : (col.has_ever_run ? "is-ok" : ""));
  const healthText  = !col.has_ever_run ? "Never run"
                    : failing ? `${failing} failing`
                    : stale ? `${stale} stale` : "All healthy";
  $("kpis").innerHTML = [
    [`Source health`, healthText, `${c.runnable} runnable unit(s)`, healthClass, true],
    [`Last successful run`, col.last_success_at ? ago(col.last_success_at) : "Never",
      col.last_success_at ? when(col.last_success_at) : "no source has ever succeeded",
      col.last_success_at ? "" : "is-warn", true],
    [`Free giveaways`, c.current_giveaways, "currently claimable", "", false],
    [`Subscription events`, c.current_subscriptions, "catalog additions & claims", "", false],
    [`Breakout releases`, c.breakouts, "highly-rated new games", "", false],
    [`Steam deals`, c.deals, "well-reviewed discounts", "", false]
  ].map(([l,v,n,cls,small]) => `<div class="kpi ${cls}">
      <div class="kpi-label">${l}</div>
      <div class="kpi-value ${small?"sm":""}">${esc(String(v))}</div>
      <div class="kpi-note">${esc(n)}</div></div>`).join("");
}

function renderBanners(){
  const s = STATE, col = s.collection, out = [];
  if(!col.run_controls_enabled){
    out.push(`<div class="notice bad"><div><div class="notice-title">Run controls unavailable</div>
      <div class="notice-text">This process was started without the operator profile, so collection
      cannot be triggered here. Start the dashboard with <span class="mono">newsroom serve</span>.</div></div></div>`);
  }
  if(!col.has_ever_run){
    out.push(`<div class="notice accent"><div><div class="notice-title">No collection has ever run against this database</div>
      <div class="notice-text">Every counter below is empty because no source has been fetched yet \\u2014 not because
      nothing was found. Press <b>Run all safe sources</b> to populate the console.
      Database: <span class="mono">${esc(col.database_path)}</span></div></div></div>`);
  } else {
    const failed = s.sources.filter(x => x.status === "error");
    if(failed.length){
      out.push(`<div class="notice bad"><div><div class="notice-title">${failed.length} source(s) failed on the last attempt</div>
        <div class="notice-text mono">${failed.map(f=>esc(f.name+": "+(f.error||"unknown error"))).join("<br>")}</div></div></div>`);
    }
    const stale = s.sources.filter(x => x.status === "stale");
    if(stale.length){
      out.push(`<div class="notice warn"><div><div class="notice-title">${stale.length} source(s) stale</div>
        <div class="notice-text">No successful fetch in ${col.stale_hours}h from:
        ${stale.map(x=>esc(x.name)).join(", ")}.</div></div></div>`);
    }
  }
  const never = s.sources.filter(x => x.status === "never_run");
  if(col.has_ever_run && never.length){
    out.push(`<div class="notice info"><div><div class="notice-title">${never.length} source(s) have never been collected</div>
      <div class="notice-text">${never.map(x=>esc(x.name)).join(", ")}</div></div></div>`);
  }
  $("banners").innerHTML = out.join("");
}

async function loadRuns(){
  try{
    const r = await fetch("/api/runs"); const d = await r.json();
    $("n-hist").textContent = d.runs.length || "";
    $("history-body").innerHTML = d.runs.length ? `<div class="tablewrap"><table class="t"><thead><tr>
      <th>Run</th><th class="num">New</th><th class="num">Ending soon</th><th class="num">Expired</th>
      <th class="num">Upcoming</th><th class="num">Suppressed</th><th>Report</th></tr></thead><tbody>` +
      d.runs.map(x => `<tr><td>${esc(when(x.generated_at))}<small>${esc(ago(x.generated_at))}</small></td>
        <td class="num">${x.new ?? "\\u2014"}</td><td class="num">${x.ending_soon ?? "\\u2014"}</td>
        <td class="num">${x.expired ?? "\\u2014"}</td><td class="num">${x.upcoming ?? "\\u2014"}</td>
        <td class="num">${x.suppressed ?? "\\u2014"}</td>
        <td class="mono dim">${esc(x.file)}</td></tr>`).join("") + `</tbody></table></div>`
      : `<div class="empty"><span class="badge info">No data yet</span>
         <div class="empty-title">No runs recorded</div>
         <p class="empty-hint">Run history is reconstructed from the report files each run writes.
         None exist yet, so no run has completed against this installation.</p></div>`;
  }catch(e){
    $("history-body").innerHTML = `<div class="empty"><div class="empty-title">Run history unavailable</div>
      <p class="empty-hint mono">${esc(String(e))}</p></div>`;
  }
}

async function loadScheduler(){
  try{
    const s = await (await fetch("/api/scheduler")).json();
    let txt;
    if(!s.supported) txt = "Scheduler: " + s.note;
    else if(!s.known) txt = "Scheduler: no task registered";
    else txt = `Scheduler: ${s.task} \\u2014 ${s.state||"?"}` +
               (s.next_run ? ` \\u00b7 next ${s.next_run}` : "") +
               (s.last_run ? ` \\u00b7 last ${s.last_run}` : "");
    $("foot-sched").textContent = txt;
    // Its own container: load() rewrites #banners on every poll and would
    // otherwise wipe this out a moment after it appeared.
    const inactive = s.supported && s.known && s.state &&
      !["ready","running"].includes(s.state.toLowerCase());
    $("banners-sched").innerHTML = inactive
      ? `<div class="notice warn"><div><div class="notice-title">Scheduled collection is not active</div>
         <div class="notice-text">The task <span class="mono">${esc(s.task)}</span> is
         <b>${esc(s.state)}</b>, so no automatic collection is happening. This console never changes
         scheduler state \\u2014 fix it in Task Scheduler, or run collection manually below.</div></div></div>`
      : "";
  }catch(e){ $("foot-sched").textContent = ""; }
}

async function load(){
  const s = await (await fetch("/api/state")).json();
  STATE = s;
  const col = s.collection, c = s.counts;

  RUNNING = col.run.status === "running";
  $("tb-run").innerHTML = RUNNING
    ? `<span class="badge warn">Collection running</span>`
    : (col.run.outcome === "error" ? `<span class="badge bad">Last run failed</span>` : "");
  $("tb-last").textContent = col.last_attempt_at
    ? "last attempt " + ago(col.last_attempt_at) : "never collected";
  $("subtitle").textContent = col.has_ever_run
    ? `Last successful collection ${ago(col.last_success_at)} \\u00b7 ${c.runnable} runnable source(s) \\u00b7 stale after ${col.stale_hours}h`
    : "No collection has run yet on this installation.";
  $("foot-db").textContent = "DB: " + col.database_path;

  $("n-src").textContent = s.sources.length;
  $("n-give").textContent = c.current_giveaways || "";
  $("n-subs").textContent = c.current_subscriptions || "";
  $("n-break").textContent = c.breakouts || "";
  $("n-deals").textContent = c.deals || "";
  $("n-up").textContent = c.upcoming || "";

  renderKpis(); renderBanners(); renderSources();

  const live = g => g.bucket !== "expired";
  const give = s.giveaways.filter(g => !g.is_subscription && live(g));
  const subs = s.giveaways.filter(g => g.is_subscription && live(g));

  renderSection("giveaways-body","giveaways-sub", s.sections.giveaways, give.length,
    `<div class="tablewrap"><table class="t"><thead><tr><th>Store</th><th>Game</th><th>Label</th>
     <th>MSRP</th><th>Ends</th></tr></thead><tbody>` +
     give.map(g => `<tr><td class="dim">${esc(g.source)}</td>
       <td><a href="${esc(g.url)}" target="_blank" rel="noopener">${esc(g.title)}</a></td>
       <td><span class="badge accent plain">${esc(g.label)}</span></td>
       <td class="num">${money(g.original_price)}</td>
       <td class="dim">${g.display_end ? esc(g.display_end.slice(0,10)) : "\\u2014"}</td></tr>`).join("") +
     `</tbody></table></div>`);

  renderSection("subscriptions-body","subscriptions-sub", s.sections.subscriptions, subs.length,
    `<div class="tablewrap"><table class="t"><thead><tr><th>Service</th><th>Game</th>
     <th>Timeline</th><th>Type</th></tr></thead><tbody>` +
     subs.map(g => `<tr><td class="dim">${esc(g.source)}</td>
       <td><a href="${esc(g.url)}" target="_blank" rel="noopener">${esc(g.title)}</a></td>
       <td class="dim">${g.display_start ? esc(g.display_start.slice(0,10)) : "\\u2014"} \\u2192 ${g.display_end ? esc(g.display_end.slice(0,10)) : "\\u2014"}</td>
       <td><span class="badge info plain">${esc(g.label)}</span></td></tr>`).join("") +
     `</tbody></table></div>`);

  renderBreakouts();

  renderSection("deals-body","deals-sub", s.sections.deals, s.deals.length,
    `<div class="tablewrap"><table class="t"><thead><tr><th>Game</th><th class="num">Off</th>
     <th class="num">Price</th><th>Reviews</th><th class="num">Count</th><th>Ends</th>
     </tr></thead><tbody>` +
     s.deals.map(d => `<tr><td><a href="${esc(d.url)}" target="_blank" rel="noopener">${esc(d.name)}</a></td>
       <td class="num">-${d.discount_percent}%</td>
       <td class="num">${d.final_price!=null ? money(d.final_price)+' <span class="muted">'+money(d.original_price)+'</span>' : "\\u2014"}</td>
       <td class="dim">${esc(d.review_desc)}</td>
       <td class="num">${d.total_reviews.toLocaleString()}</td>
       <td class="dim">${d.discount_end ? esc(d.discount_end) : "\\u2014"}</td></tr>`).join("") +
     `</tbody></table></div>`);

  renderSection("upcoming-body","upcoming-sub", s.sections.upcoming, s.upcoming.length,
    `<div class="tablewrap"><table class="t"><thead><tr><th>Game</th><th>Free from</th>
     </tr></thead><tbody>` +
     s.upcoming.map(u => `<tr><td><a href="${esc(u.url)}" target="_blank" rel="noopener">${esc(u.title)}</a></td>
       <td class="dim">${u.starts ? esc(u.starts.slice(0,10)) : "\\u2014"}</td></tr>`).join("") +
     `</tbody></table></div>`);

  $("run-all").disabled = RUNNING || !col.run_controls_enabled;
  $("run-all").textContent = RUNNING ? "Running\\u2026" : "Run all safe sources";
}

async function runNow(sources){
  if(RUNNING) return;
  RUNNING = true;
  $("run-all").disabled = true;
  $("run-all").textContent = "Running\\u2026";
  document.querySelectorAll("[data-run]").forEach(b => b.disabled = true);
  const label = sources ? sources.join(", ") : "all safe sources";
  $("run-msg").textContent = `Collecting ${label}\\u2026 this can take a few minutes.`;
  try{
    const r = await fetch("/api/run", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify(sources ? {sources} : {})
    });
    const text = await r.text();
    let d = null; try{ d = JSON.parse(text); }catch(_){}
    if(r.status === 409){
      $("run-msg").textContent = "BUSY \\u2014 " + ((d&&d.error) || "a run is already in progress.");
    } else if(!r.ok){
      $("run-msg").textContent = `Run failed (${r.status}): ${(d&&d.error)||text}`;
    } else {
      const x = d.summary;
      $("run-msg").textContent = `Done: ${x.new} new, ${x.ending_soon} ending soon, ` +
        `${x.expired} no longer free, ${x.breakouts_new} new breakout(s), ${x.deals_new} new deal(s).`;
    }
  }catch(e){ $("run-msg").textContent = "Run failed: " + e; }
  RUNNING = false;
  await load(); await loadRuns();
}

$("run-all").addEventListener("click", () => runNow(null));
load(); loadRuns(); loadScheduler();
setInterval(() => { if(!RUNNING) load(); }, 30000);
</script>
</body>
</html>
"""


@app.get("/api/discovery")
def api_discovery(include_baseline: bool = False) -> dict[str, Any]:
    from newsroom.database import load_discovery_observations
    return {"delivery": "blocked", "novelty": "unconfirmed",
            "observations": load_discovery_observations(include_baseline=include_baseline)}


@app.get("/discovery", response_class=HTMLResponse)
def discovery_page(include_baseline: bool = False) -> str:
    from html import escape
    from newsroom.database import load_discovery_observations
    rows = load_discovery_observations(include_baseline=include_baseline)
    cards = []
    for row in rows:
        links = row["evidence"][-1].get("outbound_links", [])
        provenance = " ".join(f'<a href="{escape(u, quote=True)}" rel="noreferrer">Linked evidence</a>'
                              for u in links)
        lane = "INTEL" if row["source"] == "reddit_gaming_leaks" else "Discovery"
        cards.append(f'<article class="panel"><div class="panel-body"><h2 class="panel-title"><a href="{escape(row["url"], quote=True)}">'
                     f'{escape(row["title"])}</a></h2><p>{escape(lane)} · {escape(row["classification"])} · '
                     f'{"Baseline" if row["baseline"] else "Observation; novelty unconfirmed"}'
                     f'</p>{provenance}<p>Related observations: '
                     f'{escape(chr(44).join(row["related_observation_ids"])) or "none in this view"}'
                     f'</p></div></article>')
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><title>Discovery evidence</title>'
            '<style>' + _PAGE.split('<style>', 1)[1].split('</style>', 1)[0] + '</style>'
            '<main class="main"><div class="wrap"><a href="/">Back to collector</a>'
            '<h1 class="page-title">Discovery evidence</h1>'
            '<p>Community reports are unverified. Delivery is blocked. Reddit publication time '
            'does not establish a game announcement or a live giveaway. INTEL observations are '
            'unverified rumours, not free-game or promotion events.</p>'
            '<p><a href="/discovery">Exclude baseline</a> · '
            '<a href="/discovery?include_baseline=true">Inspect full history</a></p>'
            + (''.join(cards) or '<p>No observations in this view.</p>') + '</div></main></html>')
