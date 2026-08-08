"""
Base abstraction for all news sources.

Every source plugin implements SourcePlugin.
This ensures consistency and makes the system extensible.
"""

from abc import ABC, abstractmethod

from loguru import logger

from newsroom_intelligence.models import NewsEvent


class SourcePlugin(ABC):
    """
    Abstract base class for all news sources.

    A source plugin fetches raw data from an external source,
    validates it, normalizes it into NewsEvent objects,
    and returns them to the pipeline.

    Responsibilities:
    - Fetch data from source (HTTP, API, RSS, etc.)
    - Parse and normalize into NewsEvent objects
    - Validate data quality
    - Handle timeouts and rate limits
    - Log errors gracefully

    Non-Responsibilities:
    - Storing data (pipeline handles storage)
    - Change detection (pipeline handles comparison)
    - Scoring (pipeline handles scoring)
    - Notifications (pipeline handles notifications)
    """

    def __init__(self, name: str, timeout_seconds: int = 30):
        """
        Initialize a source plugin.

        Args:
            name: Unique identifier for this source (e.g., 'epic_games', 'steam')
            timeout_seconds: HTTP request timeout
        """
        self.name = name
        self.timeout_seconds = timeout_seconds
        self.logger = logger.bind(source=name)

    @abstractmethod
    def fetch(self) -> list[NewsEvent]:
        """
        Fetch and return all news events from this source.

        Must be idempotent: calling twice without state changes
        should return identical results.

        Returns:
            List of NewsEvent objects representing current state of source.

        Raises:
            SourceError: If the source cannot be reached or parsed.
        """
        raise NotImplementedError

    @abstractmethod
    def validate(self, event: NewsEvent) -> bool:
        """
        Validate a NewsEvent before returning it.

        Checks:
        - Required fields for this source type
        - Data format correctness
        - Price/timing consistency
        - URL validity

        Args:
            event: NewsEvent to validate

        Returns:
            True if valid, False otherwise
        """
        raise NotImplementedError

    def normalize(self, raw_data: dict) -> NewsEvent | None:
        """
        Convert raw source data into a NewsEvent.

        Override in subclass to implement source-specific normalization.

        Args:
            raw_data: Dictionary from the source (JSON, parsed HTML, etc.)

        Returns:
            NewsEvent if successfully normalized, None if invalid.
        """
        raise NotImplementedError


class SourceError(Exception):
    """Raised when a source cannot be fetched or parsed."""

    pass


class SourceValidationError(Exception):
    """Raised when a NewsEvent fails validation."""

    pass
