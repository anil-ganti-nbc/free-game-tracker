"""The command-line interface.

Commands: ``version``, ``init-db``, ``fetch`` (print one source's current free
games), and ``run`` (the full fetch → compare → store → report pipeline).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from newsroom import __version__
from newsroom.compare import DEFAULT_ENDING_SOON_HOURS, RunDiff, compare, deduplicate
from newsroom.config import settings
from newsroom.database import (
    SourceHealth,
    init_db,
    load_all_events,
    load_deals,
    load_new_releases,
    load_source_health,
    record_source_result,
    sync_deals,
    sync_events,
    sync_new_releases,
)
from newsroom.models import NewsEvent, UpcomingGame
from newsroom.notify import (
    notify_new_breakouts,
    notify_new_deals,
    notify_new_giveaways,
)
from newsroom.quality import filter_events
from newsroom.report import prune_old_reports, write_reports
from newsroom.sources import (
    epic,
    gamerpower,
    geforce_now,
    gog,
    playstation_plus,
    steam,
    steam_breakouts,
    steam_deals,
    xbox_game_pass,
)
from newsroom.sources._http import SourceError

logger = logging.getLogger(__name__)

app = typer.Typer(
    add_completion=False,
    help="Newsroom — detect newly free PC games. Facts and evidence only.",
)
console = Console()

#: The sources wired up so far. Grows as sensors are added.
_SOURCES = {
    "epic": epic.fetch_free_games,
    "steam": steam.fetch_free_games,
    "gog": gog.fetch_free_games,
    "gamerpower": gamerpower.fetch_free_games,
    "playstation_plus": playstation_plus.fetch_events,
    "xbox_game_pass": xbox_game_pass.fetch_events,
    "geforce_now": geforce_now.fetch_events,
}


def _configure_logging(verbose: bool = False) -> None:
    """Set up root logging. ``--verbose`` forces DEBUG regardless of config."""
    level = "DEBUG" if verbose else settings.log_level.upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    )


def _fetch_all_sources(selected: list[str] | None) -> tuple[list[NewsEvent], set[str]]:
    """Fetch from the selected sources (all when ``selected`` is empty/None).

    Each source is isolated: whether it raises the expected ``SourceError`` or an
    unexpected exception, it is logged and skipped so one broken sensor can never
    abort the run. This is the resilience the brief asks for — the tool polls a
    handful of sites and must survive any single one misbehaving.
    """
    names = selected or list(_SOURCES)
    events: list[NewsEvent] = []
    successful_sources = set()
    for name in names:
        fetcher = _SOURCES.get(name)
        if fetcher is None:
            console.print(f"[yellow]Unknown source skipped:[/yellow] {name}")
            continue
        try:
            fetched = fetcher()
        except SourceError as error:
            logger.warning("Source %s failed: %s", name, error)
            console.print(f"[yellow]{name} skipped:[/yellow] {error}")
            record_source_result(name, ok=False, error=str(error))
        except Exception as error:  # noqa: BLE001 - a broken sensor must not abort the run
            logger.exception("Source %s raised an unexpected error", name)
            console.print(f"[yellow]{name} skipped:[/yellow] unexpected error (see logs)")
            record_source_result(name, ok=False, error=repr(error))
        else:
            record_source_result(name, ok=True, count=len(fetched))
            successful_sources.add(name)
            events.extend(fetched)
    return events, successful_sources


def _stale_sources(health: list[SourceHealth], stale_hours: int) -> list[str]:
    """Names of sources that have not fetched successfully within the window."""
    cutoff = datetime.now(UTC) - timedelta(hours=stale_hours)
    return [h.source for h in health if h.last_success_at is None or h.last_success_at < cutoff]


@app.command("init-db")
def init_db_command() -> None:
    """Create the SQLite database and tables."""
    _configure_logging()
    init_db()
    console.print(f"[green]Database ready[/green] at {settings.database_path}")


def _print_events(events: list[NewsEvent]) -> None:
    """Render detected events as a Rich table of facts."""
    if not events:
        console.print("[dim]No free games detected.[/dim]")
        return
    table = Table(title="Free game candidates")
    table.add_column("Store")
    table.add_column("Game")
    table.add_column("MSRP", justify="right")
    table.add_column("Ends")
    table.add_column("Conf.", justify="right")
    for event in events:
        table.add_row(
            event.source.value,
            event.title,
            f"{event.original_price:.2f}" if event.original_price else "—",
            event.promotion_end.date().isoformat() if event.promotion_end else "—",
            str(event.confidence.score),
        )
    console.print(table)


@app.command()
def fetch(
    source: str = typer.Argument("epic", help="Which source to fetch (e.g. epic)."),
) -> None:
    """Fetch and print current free games from one source. Does not store anything."""
    _configure_logging()
    fetcher = _SOURCES.get(source)
    if fetcher is None:
        console.print(f"[red]Unknown source:[/red] {source} (known: {', '.join(_SOURCES)})")
        raise typer.Exit(code=1)
    try:
        events = fetcher()
    except SourceError as error:
        console.print(f"[red]Fetch failed:[/red] {error}")
        raise typer.Exit(code=1) from error
    _print_events(events)


def _apply_quality_gate(diff: RunDiff) -> tuple[RunDiff, int]:
    """Filter what surfaces (new + ending soon) through the configured gate.

    Returns the surfaced diff and the number of detections suppressed. Expired
    events are informational and pass through unfiltered. Storage is untouched —
    the database still holds every detection.
    """

    def _gated(events: list[NewsEvent]) -> list[NewsEvent]:
        return filter_events(
            events,
            min_confidence=settings.min_confidence,
            min_price=settings.min_price,
            require_known_price=settings.require_known_price,
        )

    new = _gated(diff.new)
    ending_soon = _gated(diff.ending_soon)
    suppressed = (len(diff.new) - len(new)) + (len(diff.ending_soon) - len(ending_soon))
    surfaced = RunDiff(new=new, ending_soon=ending_soon, expired=diff.expired)
    return surfaced, suppressed


def _fetch_upcoming(selected: list[str] | None) -> list[UpcomingGame]:
    """Fetch Epic's upcoming free games (report-only), tolerating failure."""
    names = selected or list(_SOURCES)
    if "epic" not in names:
        return []
    try:
        return epic.fetch_upcoming_free_games()
    except SourceError as error:
        logger.warning("Epic upcoming fetch failed: %s", error)
    except Exception:  # noqa: BLE001 - upcoming is a nice-to-have, never fatal
        logger.exception("Epic upcoming fetch raised an unexpected error")
    return []


def _execute_run(
    current_events: list[NewsEvent],
    generated_at: datetime,
    ending_soon_hours: int = DEFAULT_ENDING_SOON_HOURS,
    persist: bool = True,
    upcoming: list[UpcomingGame] | None = None,
    successful_sources: set[str] | None = None,
) -> tuple[RunDiff, Path, Path]:
    """Compare against the previous run, optionally persist, and write reports."""
    current_events = deduplicate(current_events)
    previous_events = load_all_events()

    # Do not expire items from sources that were not successfully fetched.
    if successful_sources is not None:
        previous_events = [e for e in previous_events if e.source.value in successful_sources]

    diff = compare(previous_events, current_events, ending_soon_hours=ending_soon_hours)
    if persist:
        sync_events(current_events, successful_sources=successful_sources)
    surfaced, suppressed = _apply_quality_gate(diff)
    markdown_path, json_path = write_reports(
        surfaced,
        settings.reports_dir,
        generated_at,
        suppressed=suppressed,
        upcoming=upcoming,
    )
    prune_old_reports(settings.reports_dir, settings.report_retention_days)
    return surfaced, markdown_path, json_path


def _run_breakouts(now: datetime, persist: bool, do_notify: bool) -> int:
    """Trawl Steam breakouts, store, and notify new ones. Returns count of new.

    Fully fault-isolated and health-tracked; a failure here never affects the
    free-game run.
    """
    if not settings.enable_breakouts:
        return 0
    try:
        previous_ids = {r.appid for r in load_new_releases()}
        current = steam_breakouts.fetch_breakouts(
            now=now,
            max_days=settings.breakout_max_days,
            min_tier=settings.breakout_min_review_tier,
        )
    except SourceError as error:
        logger.warning("Breakout trawl failed: %s", error)
        record_source_result("steam_breakouts", ok=False, error=str(error))
        return 0
    except Exception as error:  # noqa: BLE001 - never let breakouts break a run
        logger.exception("Breakout trawl raised an unexpected error")
        record_source_result("steam_breakouts", ok=False, error=repr(error))
        return 0

    record_source_result("steam_breakouts", ok=True, count=len(current))
    new_ones = [r for r in current if r.appid not in previous_ids]
    if persist:
        sync_new_releases(current)
        if do_notify and new_ones:
            notify_new_breakouts(new_ones, webhook_url=settings.discord_webhook_url)
    return len(new_ones)


def _run_deals(persist: bool, do_notify: bool) -> int:
    """Trawl Steam deals, store, and notify new ones. Returns count of new.

    Fault-isolated and health-tracked as source 'steam_deals'.
    """
    if not settings.enable_deals:
        return 0
    try:
        previous_ids = {d.appid for d in load_deals()}
        current = steam_deals.fetch_deals(
            min_discount=settings.deal_min_discount_percent,
            min_tier=settings.deal_min_review_tier,
            min_reviews=settings.deal_min_reviews,
        )
    except SourceError as error:
        logger.warning("Deals trawl failed: %s", error)
        record_source_result("steam_deals", ok=False, error=str(error))
        return 0
    except Exception as error:  # noqa: BLE001 - never let deals break a run
        logger.exception("Deals trawl raised an unexpected error")
        record_source_result("steam_deals", ok=False, error=repr(error))
        return 0

    record_source_result("steam_deals", ok=True, count=len(current))
    new_ones = [d for d in current if d.appid not in previous_ids]
    if persist:
        sync_deals(current)
        if do_notify and new_ones:
            notify_new_deals(new_ones, webhook_url=settings.discord_webhook_url)
    return len(new_ones)


def run_pipeline(
    selected: list[str] | None = None,
    ending_soon_hours: int = DEFAULT_ENDING_SOON_HOURS,
    persist: bool = True,
    do_notify: bool = True,
) -> dict[str, Any]:
    """Run one full detection cycle and return a summary."""
    init_db()
    generated_at = datetime.now(UTC)

    current_events, successful_sources = _fetch_all_sources(selected)
    upcoming = _fetch_upcoming(selected)
    diff, markdown_path, json_path = _execute_run(
        current_events,
        generated_at,
        ending_soon_hours,
        persist=persist,
        upcoming=upcoming,
        successful_sources=successful_sources,
    )
    if persist and do_notify:
        notify_new_giveaways(diff, webhook_url=settings.discord_webhook_url)

    breakouts_new = _run_breakouts(generated_at, persist, do_notify)
    deals_new = _run_deals(persist, do_notify)

    stale = _stale_sources(load_source_health(), settings.source_stale_hours)
    return {
        "new": len(diff.new),
        "ending_soon": len(diff.ending_soon),
        "expired": len(diff.expired),
        "upcoming": len(upcoming),
        "breakouts_new": breakouts_new,
        "deals_new": deals_new,
        "markdown_path": str(markdown_path),
        "json_path": str(json_path),
        "stale": stale,
    }


@app.command()
def run(
    source: list[str] | None = typer.Option(
        None, "--source", help="Limit to these sources (repeatable). Default: all."
    ),
    ending_soon_hours: int = typer.Option(
        DEFAULT_ENDING_SOON_HOURS,
        help="Flag continuing promotions ending within this many hours.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Do everything except write to the database."
    ),
    no_notify: bool = typer.Option(
        False, "--no-notify", help="Skip the Discord notification for this run."
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Run one detection cycle: fetch every source, compare, store, and report.

    Any source that fails — expectedly or not — is logged and skipped; the run
    still completes with whatever the other sources returned.
    """
    _configure_logging(verbose)
    summary = run_pipeline(
        selected=source,
        ending_soon_hours=ending_soon_hours,
        persist=not dry_run,
        do_notify=not no_notify,
    )

    persisted = "" if not dry_run else " [dim](dry run — nothing stored)[/dim]"
    console.print(
        f"[green]Run complete.[/green]{persisted} {summary['new']} new, "
        f"{summary['ending_soon']} ending soon, {summary['expired']} no longer free, "
        f"{summary['breakouts_new']} new breakout(s), {summary['deals_new']} new deal(s)."
    )
    console.print(f"Reports written:\n  {summary['markdown_path']}\n  {summary['json_path']}")
    if summary["stale"]:
        console.print(
            f"[yellow]Warning:[/yellow] no successful fetch in "
            f"{settings.source_stale_hours}h from: {', '.join(summary['stale'])}"
        )


@app.command()
def status() -> None:
    """Show last-run info, stored giveaways, and per-source health."""
    _configure_logging()
    init_db()

    stored = load_all_events()
    health = load_source_health()
    console.print(f"Stored giveaways: [bold]{len(stored)}[/bold]")
    if health:
        last_run = max(h.last_attempt_at for h in health)
        console.print(f"Last run: {last_run.isoformat()}")
    else:
        console.print("[dim]No runs recorded yet.[/dim]")
        return

    stale = set(_stale_sources(health, settings.source_stale_hours))
    table = Table(title="Source health")
    table.add_column("Source")
    table.add_column("Status")
    table.add_column("Last success")
    table.add_column("Games", justify="right")
    for h in sorted(health, key=lambda x: x.source):
        status_label = "ok" if h.last_status == "ok" else "ERROR"
        if h.source in stale:
            status_label += " (stale)"
        last_ok = h.last_success_at.isoformat() if h.last_success_at else "never"
        table.add_row(h.source, status_label, last_ok, str(h.last_count))
    console.print(table)
    if stale:
        console.print(
            f"[yellow]Stale sources (no success in {settings.source_stale_hours}h):"
            f"[/yellow] {', '.join(sorted(stale))}"
        )


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Address to bind. Localhost by default."),
    port: int = typer.Option(8765, help="Port to serve the dashboard on."),
) -> None:
    """Launch the local web dashboard (requires the 'gui' extra)."""
    _configure_logging()
    init_db()
    try:
        import uvicorn

        from newsroom.webapp import app as web_app
    except ModuleNotFoundError as error:
        console.print(
            "[red]The dashboard needs extra packages.[/red] "
            "Install them with: [bold]uv sync --extra gui[/bold]"
        )
        raise typer.Exit(code=1) from error

    console.print(f"Dashboard at [bold]http://{host}:{port}[/bold]  (Ctrl+C to stop)")
    uvicorn.run(web_app, host=host, port=port, log_level=settings.log_level.lower())


@app.command()
def version() -> None:
    """Print the application version."""
    console.print(f"newsroom {__version__}")
