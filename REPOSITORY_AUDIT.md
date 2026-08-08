# Repository Audit: Free Game Tracker (Newsroom)

## 1. Overview
The **Newsroom** application is an internal sensor script that tracks PC games given away for free (and notable well-reviewed discounted or freshly released games) across prominent PC gaming platforms like Epic Games Store, Steam, GOG, and aggregates like GamerPower. It fetches this data, compares the state against previous runs using an SQLite database via SQLAlchemy, generates structured reports (Markdown/JSON) of newly free games, and optionally pushes to a Discord Webhook. The application is built in Python using Typer as the CLI framework, FastAPI for a local dashboard GUI, and Pydantic for defining robust domain models.

## 2. Application Entry Point
- The application begins execution through `newsroom/main.py`, which is hooked as the main executable script.
- That script defers to a Typer CLI application built inside `newsroom/cli.py`.
- Users run commands utilizing `uv run newsroom <command>`. The core orchestration logic lives in the `run_pipeline()` method inside `cli.py` which sequences data collection, differencing, database inserts, notifications, and web report generation.

## 3. End-to-End Collector Trace: Epic Games
Tracing the Epic Games collector (`newsroom/sources/epic.py`):
1. **Network Layer:** Execution begins at `epic.fetch_free_games()`. It conducts HTTP operations against an external JSON endpoint (`https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions`). Handled with retry mechanics via `fetch_json()`, raising `SourceError` natively safely on any issues.
2. **Parsing & Normalization:** Natively decodes payload passing it to `parse_free_games()`. The algorithm recursively iterates through `.data.Catalog.searchStore.elements`, ignoring missing items safely.
3. **Filtering & Extraction:** It explicitly ignores bundles and expansions looking for native tags (e.g., `ADD_ON`), normalizes promotional bounds validating if `.discountPercentage` == `0`, and binds missing fields.
4. **Domain Wrapping:** Computes confidence scores explicitly detailing why specific scores were applied based on absent information, parsing all discoveries cleanly into uncoupled Pydantic-based `NewsEvent` objects that the whole backend uniformly accepts.

## 4. Database Schema
Defined structurally via SQLAlchemy mapped ORMs on an SQLite database (`newsroom.db`) inside `newsroom/database.py`.
- **`news_events` (`NewsEventRow`)**: Core domain objects mirroring `NewsEvent`. Tracks source origins, URL scopes, titles, prices, starts/ends boundaries, and captures "First Discovered" markers natively by using an indexed `event_key`.
- **`source_health` (`SourceHealthRow`)**: Traces runtime statuses of collectors, maintaining audit trails for broken connections ensuring the dashboard dynamically identifies heavily stale components.
- **`new_releases` (`NewReleaseRow`)**: Tracks breakout Steam releases (strong reviews on rapidly launched titles) mapping native Steam AppIDs and review bounds natively resolving staleness.
- **`steam_deals` (`SteamDealRow`)**: Keeps records of deeply discounted but highly-reviewed Steam games indexed heavily around localized final pricing and discount ratios.

## 5. Notification Pipeline
The Discord alerting workflow runs strictly isolated in `newsroom/notify.py`:
- Right after the compare steps inside `run_pipeline()`, the payload `diff` resolves native state mutations isolating `diff.new` sets (newly discovered facts this cycle).
- The `notify_new_giveaways()` iterates newly discovered events explicitly gating promotions below the `min_confidence` scores dynamically configured by `.env`.
- Builds localized Discord Embeds arrays mapping titles, bounding variables, confidence ratios padding dynamically to lists compliant with a 10-Embed ceiling set by Discord API limits natively (`build_discord_payload`). 
- Features advanced native network limits checking `Retry-After` bounds in API `429 Too Many Requests`. This mechanism isolates pipeline interruptions aggressively.
- It also implements alternative funnels mapped natively around breakouts (`notify_new_breakouts`) and promotional deals (`notify_new_deals`).

## 6. Dashboard
Implemented purely inside `newsroom/webapp.py` via a minimal `FastAPI` instance. 
- Started via the CLI command `serve`, conventionally bound on `http://127.0.0.1:8765/`.
- **Pages**: Uses no secondary frontends or framework transpilers natively serving a fully encoded vanilla HTML block rendering raw data schemas intuitively inside single table panes.
- **Endpoints:** Uses direct database transactions outputting standard JSON objects mapped around `/api/state` displaying events natively, missing source health variables, deal arrays, and headers.
- **Remote Execution:** Contains native capabilities initiating pipeline runs concurrently locked around threads targeting POST calls to `/api/run/`. 

## 7. Existing Tests & Collectors
- The repository natively tests perfectly via `.pytest_cache/` workflows ensuring strict validation via `uv run pytest`.
- System natively relies on explicit module-scoped collectors located inside `/sources/` dir natively binding to: `epic.py`, `gamerpower.py`, `gog.py`, `steam.py`, `steam_breakouts.py` and `steam_deals.py`.

## 8. Adding a New Collector
To implement a custom tracker mapping natively:
1. Append a new source identifier entry inside the Enum `Source` natively configured in `newsroom/models.py`.
2. Author your collector inside `newsroom/sources/` globally exposing an entry function signature functionally matching returning array schemas of `list[NewsEvent]`. Keep the sensor decoupled mapping purely from raw structures straight into validated domain sets.
3. Hook initialization locally inside `_SOURCES` dictionary structure mapped on top of `newsroom/cli.py` integrating pipelines dynamically targeting your endpoint directly.
