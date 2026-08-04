"""Application configuration.

Settings come from environment variables (optionally via a ``.env`` file). We
keep this small: only values that a real deployment would plausibly want to
change live here. Everything is typed and validated by Pydantic at load time, so
a bad setting fails immediately with a clear message.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# The project root is the directory that contains the ``newsroom`` package.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime configuration, loaded from the environment and ``.env``.

    Attributes are read once at import time into the module-level ``settings``
    singleton. Prefix every environment variable with ``NEWSROOM_`` — for
    example ``NEWSROOM_LOG_LEVEL=DEBUG``.
    """

    model_config = SettingsConfigDict(
        env_prefix="NEWSROOM_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Storage ------------------------------------------------------------
    database_path: Path = Field(
        default=PROJECT_ROOT / "newsroom.db",
        description="Filesystem path to the SQLite database file.",
    )
    database_echo: bool = Field(
        default=False,
        description="If true, SQLAlchemy logs every SQL statement. Noisy; dev only.",
    )

    # --- HTTP (used by sources from Milestone 2 onward) ---------------------
    http_timeout_seconds: float = Field(
        default=30.0, gt=0, description="Per-request timeout for source fetches."
    )
    http_max_retries: int = Field(
        default=3, ge=0, description="How many times to retry a failed fetch."
    )
    http_retry_backoff_seconds: float = Field(
        default=2.0, ge=0, description="Base delay between retries (grows per attempt)."
    )

    # --- Reporting ----------------------------------------------------------
    reports_dir: Path = Field(
        default=PROJECT_ROOT / "reports",
        description="Directory where Markdown and JSON reports are written.",
    )
    report_retention_days: int = Field(
        default=30,
        ge=0,
        description="Delete reports older than this many days (0 = keep forever).",
    )

    # --- Health -------------------------------------------------------------
    source_stale_hours: int = Field(
        default=6,
        ge=1,
        description="Warn if a source has not fetched successfully in this long.",
    )

    # --- Breakout new releases (Steam) --------------------------------------
    enable_breakouts: bool = Field(
        default=True,
        description="Trawl Steam new releases for highly-rated breakout games.",
    )
    breakout_max_days: int = Field(
        default=14,
        ge=1,
        le=60,
        description="Only consider games released within this many days.",
    )
    breakout_min_review_tier: str = Field(
        default="Very Positive",
        description="Minimum Steam review tier to surface (e.g. 'Very Positive').",
    )

    # --- Steam deals --------------------------------------------------------
    enable_deals: bool = Field(
        default=True,
        description="Trawl Steam specials for well-reviewed discounted games.",
    )
    deal_min_discount_percent: int = Field(
        default=30,
        ge=1,
        le=99,
        description="Minimum discount to surface (100% off is handled as free).",
    )
    deal_min_review_tier: str = Field(
        default="Mixed",
        description="Minimum Steam review tier for a deal (e.g. 'Mixed').",
    )
    deal_min_reviews: int = Field(
        default=1000,
        ge=0,
        description="Minimum review count so thinly-reviewed shovelware is excluded.",
    )

    # --- Source tuning ------------------------------------------------------
    gamerpower_utc_offset_hours: int = Field(
        default=0,
        description=(
            "Hours to add to GamerPower end dates before treating them as UTC. "
            "GamerPower does not state a timezone; adjust if 'ending soon' drifts."
        ),
    )

    # --- Logging ------------------------------------------------------------
    log_level: str = Field(
        default="INFO",
        description="Root log level (DEBUG, INFO, WARNING, ERROR).",
    )

    # --- Notifications ------------------------------------------------------
    discord_webhook_url: str | None = Field(
        default=None,
        description="If set, newly free games are posted to this Discord webhook.",
    )

    # --- Quality gate (what surfaces to reports and notifications) ----------
    # The database always keeps the full record; these only affect what is
    # shown to the editor, to keep low-value "nothingburgers" out of the way.
    min_confidence: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Only surface detections at or above this confidence.",
    )
    min_price: float = Field(
        default=0.0,
        ge=0,
        description="Only surface games whose known MSRP is at least this.",
    )
    require_known_price: bool = Field(
        default=False,
        description="Suppress giveaways that have no real (non-zero) MSRP.",
    )

    @property
    def database_url(self) -> str:
        """The SQLAlchemy URL for the configured SQLite file."""
        return f"sqlite:///{self.database_path}"


# A single shared instance. Import this, do not construct Settings elsewhere.
settings = Settings()
