"""
Configuration management.

Loads settings from environment variables and config files.
"""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Application settings.

    Load from environment variables or .env file.
    """

    # Application
    app_name: str = "newsroom-intelligence"
    app_version: str = "0.1.0"
    debug: bool = False

    # Logging
    log_level: str = "INFO"
    log_file: str | None = None

    # Database
    database_url: str = "sqlite:///./newsroom.db"
    database_echo: bool = False

    # Sources
    http_timeout: int = 30
    http_max_retries: int = 3
    http_retry_delay_seconds: float = 1.0

    # Rate limiting
    rate_limit_requests_per_minute: int = 60

    # Notifications
    discord_webhook_url: str | None = None
    notification_min_confidence: float = 0.5

    # Directories
    workspace_dir: Path = Path("/workspace/newsroom_intelligence")
    config_dir: Path = Path("/workspace/newsroom_intelligence/config")
    data_dir: Path = Path("/workspace/newsroom_intelligence/data")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Global settings instance
settings = Settings()
