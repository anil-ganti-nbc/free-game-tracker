# Database Migrations (Stage 1)

## Architecture
Because native `SQLite` strictly refuses arbitrary `ALTER TABLE` batches generated dynamically by naive scripts, we introduced **Alembic** as a dedicated offline migration utility transparently integrated on top of our `get_engine` setups.

## First-Class DB Columns
For fast indexing downstream, the following metrics were natively generated as discrete String/Datetime tables instead of JSON blobs natively:
- `event_type`, `access_model`, `ownership_model`
- `service`
- `available_from`, `available_until`, `claim_deadline`
- `day_one`

## JSON Fields
The dynamically sized elements were natively tracked as JSON mapping efficiently matching PyDantic lists seamlessly:
- `tiers`, `platforms`, `regions`, `storefronts`, `metadata`.

## Migration System
Alembic resides locally mapped under `/alembic/`.
`newsroom.db` upgrades are automatically wrapped securely beneath the standard CLI workflow.
- `newsroom init-db` checks statically if `news_events` exists previously leveraging raw SQL traces using `Inspector` natively checking `has_table`. 
- For natively clean directories, it runs `create_all()` locking explicitly and `alembic stamp` forcing structural updates preventing Alembic from crashing.
- For preexisting DB deployments missing `alembic_version`, it explicitly binds `stamp` tagging historical IDs (`87c050402d09`, the schema before stage 1) and intelligently bumps `alembic upgrade head`, dynamically binding `ALTER TABLE ADD COLUMN` transparently safely without data loss.

## Manual Executions
Standard users explicitly should not need manual upgrades! `uv run newsroom run` handles it dynamically. 
However, offline backups are always locally structured securely on `./newsroom.db` copying strictly as flat files natively supporting manual snapshots heavily locally. 
