"""
Structured logging configuration.

Uses loguru for better logging than standard library.
"""

import sys
from pathlib import Path

from loguru import logger

from newsroom_intelligence.config import settings


def setup_logging() -> None:
    """Initialize logging system."""

    # Remove default handler
    logger.remove()

    # Console output
    logger.add(
        sys.stderr,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
        level=settings.log_level,
        colorize=True,
    )

    # File output (if configured)
    if settings.log_file:
        log_path = Path(settings.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        logger.add(
            log_path,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
            level=settings.log_level,
            rotation="500 MB",
            retention="7 days",
        )

    logger.info(f"Logging initialized (level={settings.log_level})")
