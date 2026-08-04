"""
Unit tests for core data models.
"""

import pytest
from datetime import datetime, timedelta

from newsroom_intelligence.models import (
    Category,
    Confidence,
    NewsEvent,
    PromotionType,
)


class TestConfidence:
    """Test Confidence score validation."""
    
    def test_valid_confidence(self):
        """Confidence between 0.0 and 1.0 should be valid."""
        assert Confidence(0.0) == 0.0
        assert Confidence(0.5) == 0.5
        assert Confidence(1.0) == 1.0
    
    def test_invalid_confidence_too_low(self):
        """Confidence below 0.0 should raise."""
        with pytest.raises(ValueError):
            Confidence(-0.1)
    
    def test_invalid_confidence_too_high(self):
        """Confidence above 1.0 should raise."""
        with pytest.raises(ValueError):
            Confidence(1.1)


class TestNewsEvent:
    """Test NewsEvent model."""
    
    def test_create_basic_event(self):
        """Create a basic NewsEvent."""
        event = NewsEvent(
            category=Category.GAME_PROMOTION,
            source="epic_games",
            title="Free Game: Cyberpunk 2077",
            url="https://example.com/game",
        )
        assert event.category == Category.GAME_PROMOTION
        assert event.source == "epic_games"
        assert event.id is not None
        assert event.discovered_at is not None
    
    def test_game_promotion_event(self):
        """Create a game promotion event with pricing."""
        event = NewsEvent(
            category=Category.GAME_PROMOTION,
            source="steam",
            title="Baldur's Gate 3 - 20% Off",
            url="https://store.steampowered.com/app/1086590",
            developer="Larian Studios",
            publisher="Larian Studios",
            promotion_type=PromotionType.DISCOUNT,
            original_price=60.0,
            current_price=48.0,
            promotion_start=datetime.utcnow(),
            promotion_end=datetime.utcnow() + timedelta(days=7),
            confidence_score=Confidence(0.95),
        )
        
        assert event.promotion_type == PromotionType.DISCOUNT
        assert event.price_reduction_percent() == pytest.approx(20.0, rel=0.01)
        assert event.days_until_expiration() is not None
        assert not event.is_expired()
    
    def test_event_expiration(self):
        """Test expiration logic."""
        past = datetime.utcnow() - timedelta(hours=1)
        event = NewsEvent(
            category=Category.GAME_PROMOTION,
            source="gog",
            title="Expired Promotion",
            url="https://example.com",
            promotion_end=past,
        )
        assert event.is_expired()
    
    def test_event_hashable(self):
        """NewsEvent should be hashable for deduplication."""
        event1 = NewsEvent(
            category=Category.GAME_PROMOTION,
            source="epic_games",
            title="Game",
            url="https://example.com/game",
        )
        event2 = NewsEvent(
            category=Category.GAME_PROMOTION,
            source="epic_games",
            title="Game",
            url="https://example.com/game",
        )
        # Different IDs, different hashes
        assert hash(event1) != hash(event2)
        
        # Can be used in sets
        event_set = {event1, event2}
        assert len(event_set) == 2
