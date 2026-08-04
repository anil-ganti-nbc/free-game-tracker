"""
Newsroom Intelligence Platform

Modular news discovery system for professional journalists.

Core modules:
- models: NewsEvent and related data structures
- source: SourcePlugin base class
- config: Configuration management
- logging: Logging setup
"""

__version__ = "0.1.0"
__author__ = "Newsroom Intelligence Team"

from newsroom_intelligence.config import settings
from newsroom_intelligence.logging import setup_logging
from newsroom_intelligence.models import Category, NewsEvent, PromotionType
from newsroom_intelligence.source import SourceError, SourcePlugin, SourceValidationError

__all__ = [
    "settings",
    "setup_logging",
    "NewsEvent",
    "Category",
    "PromotionType",
    "SourcePlugin",
    "SourceError",
    "SourceValidationError",
]
