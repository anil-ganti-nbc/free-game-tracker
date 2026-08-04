"""
Unit tests for source plugins.
"""

import pytest

from newsroom_intelligence.models import Category, NewsEvent
from newsroom_intelligence.source import SourcePlugin, SourceError


class MockSource(SourcePlugin):
    """Mock source for testing."""
    
    def __init__(self):
        super().__init__("mock_source")
        self.mock_events = []
    
    def fetch(self) -> list[NewsEvent]:
        """Return mock events."""
        return self.mock_events
    
    def validate(self, event: NewsEvent) -> bool:
        """Always valid for mock."""
        return True
    
    def normalize(self, raw_data: dict) -> NewsEvent:
        """Simple mock normalization."""
        return NewsEvent(
            category=Category.GAME_PROMOTION,
            source=self.name,
            title=raw_data.get("title", ""),
            url=raw_data.get("url", ""),
        )


class TestSourcePlugin:
    """Test source plugin base class."""
    
    def test_source_instantiation(self):
        """Create a mock source."""
        source = MockSource()
        assert source.name == "mock_source"
        assert source.timeout_seconds == 30
    
    def test_fetch_returns_list(self):
        """Fetch should return list of events."""
        source = MockSource()
        events = source.fetch()
        assert isinstance(events, list)
    
    def test_validate_implementation(self):
        """Validate should work."""
        source = MockSource()
        event = NewsEvent(
            category=Category.GAME_PROMOTION,
            source="test",
            title="Test",
            url="https://example.com",
        )
        assert source.validate(event) is True
