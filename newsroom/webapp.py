"""The local web dashboard (``newsroom serve``).

A tiny FastAPI app that turns the data we already collect into a page you can
keep open: current free giveaways, per-source health, the upcoming heads-up, and
a "Run now" button. It is purely a read/trigger layer — no new data model, no
business logic. Everything comes from the database and the existing pipeline.

Kept deliberately dependency-light: one server module, a couple of JSON
endpoints, and a single self-contained HTML page (no framework, no build step).
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from newsroom.cli import _stale_sources, run_pipeline
from newsroom.config import settings
from newsroom.database import (
    SourceHealth,
    load_all_events,
    load_deals,
    load_new_releases,
    load_source_health,
)
from newsroom.models import NewRelease, NewsEvent, SteamDeal

app = FastAPI(title="Newsroom", docs_url=None, redoc_url=None)

# Only one run at a time, whether triggered by the button or the scheduler.
_run_lock = threading.Lock()


def _serialize_event(event: NewsEvent) -> dict[str, Any]:
    return {
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
    }


def _serialize_health(health: SourceHealth, stale: bool) -> dict[str, Any]:
    return {
        "source": health.source,
        "status": health.last_status,
        "stale": stale,
        "last_success_at": (
            health.last_success_at.isoformat() if health.last_success_at else None
        ),
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


def get_state() -> dict[str, Any]:
    """Assemble the dashboard's data from the database and latest report."""
    now = datetime.now(UTC)
    events = sorted(load_all_events(), key=lambda e: (e.source.value, e.title.lower()))
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

    return {
        "generated_at": generated_at,
        "counts": {
            "giveaways": len(events),
            "sources": len(health),
            "upcoming": len(upcoming),
            "stale": len(stale),
            "breakouts": len(breakouts),
            "deals": len(deals),
        },
        "giveaways": [_serialize_event(e) for e in events],
        "health": [_serialize_health(h, h.source in stale) for h in health],
        "upcoming": upcoming,
        "breakouts": [_serialize_release(r, now) for r in breakouts],
        "deals": [_serialize_deal(d) for d in deals],
    }


@app.get("/api/state")
def api_state() -> dict[str, Any]:
    """Return the current dashboard state as JSON."""
    return get_state()


@app.post("/api/run")
def api_run() -> JSONResponse:
    """Trigger one detection cycle, unless one is already running."""
    if not _run_lock.acquire(blocking=False):
        return JSONResponse(
            {"ok": False, "error": "A run is already in progress."}, status_code=409
        )
    try:
        summary = run_pipeline()
        return JSONResponse({"ok": True, "summary": summary})
    finally:
        _run_lock.release()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """Serve the single-page dashboard."""
    return _PAGE


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Newsroom — Free Games</title>
<style>
  :root { --bg:#0f1220; --card:#1a1e33; --line:#2b3050; --text:#e8eaf5; --muted:#9aa2c0;
          --accent:#6ea8fe; --good:#2ecc71; --warn:#f1c40f; --bad:#e74c3c; }
  * { box-sizing: border-box; }
  body { margin:0; background:#0f1220; color:#e8eaf5;
         font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }
  header { display:flex; align-items:center; gap:16px; flex-wrap:wrap;
           padding:18px 24px; border-bottom:1px solid var(--line); }
  h1 { font-size:18px; margin:0; letter-spacing:.3px; }
  .muted { color:var(--muted); }
  .spacer { flex:1; }
  button { background:var(--accent); color:#08122b; border:0; border-radius:8px;
           padding:9px 16px; font-weight:600; cursor:pointer; }
  button:disabled { opacity:.5; cursor:default; }
  main { padding:24px; max-width:1100px; margin:0 auto; }
  .cards { display:flex; gap:12px; flex-wrap:wrap; margin-bottom:20px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px;
          padding:14px 18px; min-width:120px; }
  .card .n { font-size:26px; font-weight:700; }
  .card .l { color:var(--muted); font-size:13px; }
  section { margin:22px 0; }
  h2 { font-size:15px; text-transform:uppercase; letter-spacing:.6px;
       color:var(--muted); border-bottom:1px solid var(--line); padding-bottom:6px; }
  table { width:100%; border-collapse:collapse; }
  th,td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line);
          vertical-align:top; }
  th { color:var(--muted); font-weight:600; font-size:13px; }
  a { color:var(--accent); text-decoration:none; }
  a:hover { text-decoration:underline; }
  .pill { display:inline-block; padding:1px 8px; border-radius:999px; font-size:12px;
          font-weight:600; }
  .ok { background:rgba(46,204,113,.15); color:var(--good); }
  .stale, .err { background:rgba(231,76,60,.15); color:var(--bad); }
  .msg { font-size:13px; }
</style>
</head>
<body>
<header>
  <h1>📰 Newsroom <span class="muted">— free game watch</span></h1>
  <div class="spacer"></div>
  <span id="gen" class="muted"></span>
  <button id="run" onclick="runNow()">Run now</button>
</header>
<main>
  <div class="cards" id="cards"></div>
  <div id="msg" class="msg muted"></div>
  <section><h2>Current free giveaways</h2><div id="giveaways"></div></section>
  <section>
    <h2>Breakout new releases
      <span style="text-transform:none;letter-spacing:0;float:right;font-weight:400">
        within <span id="dayval">14</span> days
        <input id="days" type="range" min="1" max="14" value="14" oninput="renderBreakouts()">
      </span>
    </h2>
    <div id="breakouts"></div>
  </section>
  <section><h2>Steam deals (well-reviewed)</h2><div id="deals"></div></section>
  <section id="upcoming-wrap"><h2>Upcoming (heads-up)</h2><div id="upcoming"></div></section>
  <section><h2>Source health</h2><div id="health"></div></section>
</main>
<script>
const $ = id => document.getElementById(id);
let STATE = {breakouts: []};
function money(v){ return (v===null||v===undefined) ? "—" : ("$"+Number(v).toFixed(2)); }
function esc(s){ const d=document.createElement("div"); d.textContent=s??""; return d.innerHTML; }

function renderBreakouts(){
  const days = Number($("days").value); $("dayval").textContent = days;
  const rows = STATE.breakouts.filter(b => b.days_since <= days);
  $("breakouts").innerHTML = rows.length ? `<table>
    <tr><th>Game</th><th>Reviews</th><th>Count</th><th>Positive</th><th>Released</th><th>Age</th></tr>` +
    rows.map(b => `<tr>
      <td><a href="${esc(b.url)}" target="_blank" rel="noopener">${esc(b.name)}</a></td>
      <td>${esc(b.review_desc)}</td>
      <td>${b.total_reviews.toLocaleString()}</td>
      <td>${b.positive_pct}%</td>
      <td>${esc(b.release_date)}</td>
      <td>${b.days_since}d</td></tr>`).join("") + `</table>`
    : `<p class="muted">No breakout releases within ${days} days.</p>`;
}

async function load(){
  const r = await fetch("/api/state"); const s = await r.json(); STATE = s;
  $("gen").textContent = s.generated_at ? ("last run: "+new Date(s.generated_at).toLocaleString()) : "no runs yet";
  const c = s.counts;
  $("cards").innerHTML = [
    ["Giveaways", c.giveaways], ["Deals", c.deals], ["Breakouts", c.breakouts],
    ["Sources", c.sources], ["Upcoming", c.upcoming], ["Stale sources", c.stale]
  ].map(([l,n]) => `<div class="card"><div class="n">${n}</div><div class="l">${l}</div></div>`).join("");

  $("giveaways").innerHTML = s.giveaways.length ? `<table>
    <tr><th>Store</th><th>Game</th><th>MSRP</th><th>Ends</th><th>Conf.</th></tr>` +
    s.giveaways.map(g => `<tr>
      <td>${esc(g.source)}</td>
      <td><a href="${esc(g.url)}" target="_blank" rel="noopener">${esc(g.title)}</a></td>
      <td>${money(g.original_price)} → Free</td>
      <td>${g.promotion_end ? esc(g.promotion_end.slice(0,10)) : "—"}</td>
      <td>${g.confidence}</td></tr>`).join("") + `</table>`
    : `<p class="muted">None right now.</p>`;

  renderBreakouts();

  $("deals").innerHTML = s.deals.length ? `<table>
    <tr><th>Game</th><th>Off</th><th>Price</th><th>Reviews</th><th>Count</th><th>Ends</th></tr>` +
    s.deals.map(d => `<tr>
      <td><a href="${esc(d.url)}" target="_blank" rel="noopener">${esc(d.name)}</a></td>
      <td>-${d.discount_percent}%</td>
      <td>${d.original_price!=null && d.final_price!=null ? "$"+d.final_price.toFixed(2)+" <span class='muted'>("+money(d.original_price)+")</span>" : "—"}</td>
      <td>${esc(d.review_desc)}</td>
      <td>${d.total_reviews.toLocaleString()}</td>
      <td>${d.discount_end ? esc(d.discount_end) : "—"}</td></tr>`).join("") + `</table>`
    : `<p class="muted">No qualifying deals right now.</p>`;

  $("upcoming-wrap").style.display = s.upcoming.length ? "" : "none";
  $("upcoming").innerHTML = s.upcoming.map(u => `<div>• <a href="${esc(u.url)}" target="_blank" rel="noopener">${esc(u.title)}</a>${u.starts ? " — free from "+esc(u.starts.slice(0,10)) : ""}</div>`).join("");

  $("health").innerHTML = `<table>
    <tr><th>Source</th><th>Status</th><th>Last success</th><th>Games</th></tr>` +
    s.health.map(h => `<tr>
      <td>${esc(h.source)}</td>
      <td><span class="pill ${h.stale ? "stale" : (h.status==="ok" ? "ok":"err")}">${h.stale?"stale":esc(h.status)}</span></td>
      <td>${h.last_success_at ? new Date(h.last_success_at).toLocaleString() : "never"}</td>
      <td>${h.count}</td></tr>`).join("") + `</table>`;
}

async function runNow(){
  const b = $("run"); b.disabled = true; $("msg").textContent = "Running…";
  try {
    const r = await fetch("/api/run", {method:"POST"});
    const d = await r.json();
    if (d.ok){ const x=d.summary; $("msg").textContent = `Done: ${x.new} new, ${x.ending_soon} ending soon, ${x.expired} gone.`; }
    else { $("msg").textContent = d.error || "Run failed."; }
  } catch(e){ $("msg").textContent = "Run failed: "+e; }
  b.disabled = false; load();
}

load();
setInterval(load, 30000);
</script>
</body>
</html>
"""
