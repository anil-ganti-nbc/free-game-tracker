"""
Apple Arcade newsroom source.
"""

from newsroom.models import NewsEvent


class AppleArcadeSource:
    name = "apple_arcade"

    def fetch_events(self) -> list[NewsEvent]:
        # Stub implementation
        return []

    def get_source_url(self) -> str:
        return "https://www.apple.com/newsroom/topics/apple-arcade/"
