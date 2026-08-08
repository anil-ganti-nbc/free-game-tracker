"""GeForce NOW collector.

Discovery strategy
------------------
* Polls the official NVIDIA Blog RSS feed.
* Filters only weekly "GFN Thursday" announcement posts by title keyword.
* Parses game-list bullet items from the post body HTML.
* Rejects any bullet that does not contain a known storefront identifier.
* Emits one ``NewsEvent`` per (game_title, storefront) pair.

Ownership model
---------------
GeForce NOW is BYOG (Bring Your Own Game).  NVIDIA does not grant ownership.
Every emitted event therefore carries:
  access_model   = STREAMING_SUPPORT
  ownership_model = REQUIRES_EXTERNAL_OWNERSHIP

Storefront identity
-------------------
The same title may appear on multiple storefronts in a single post.
Each storefront variant is a distinct event with a distinct stable
``event_key`` so that monthly previews and week-of confirmations collapse
to the same identity and are never emitted twice.

Scope limits
------------
* No removals emitted.
* No Alliance-partner regional variants.
* No RTX / feature-only editorial entries.
* No GraphQL, community JSON, or private APIs used.
"""

from __future__ import annotations

import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

from bs4 import BeautifulSoup, Tag

from newsroom.models import (
    AccessModel,
    Category,
    Confidence,
    EventType,
    NewsEvent,
    OwnershipModel,
    PromotionType,
    Source,
)
from newsroom.sources._http import SourceError, fetch_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FEED_URL = "https://blogs.nvidia.com/feed/"

# Post title must contain one of these (case-insensitive) to be processed.
GFN_TITLE_SIGNALS = [
    "gfn thursday",
    "geforce now thursday",
    "this week on geforce now",
    "geforce now adds",
    "games joining geforce now",
]

# Valid storefronts and their canonical normalised labels.
# Longest / most specific entries first avoids partial-match shadowing.
_STOREFRONT_PATTERNS: list[tuple[str, str]] = [
    (r"epic\s+games?\s+store", "epic"),
    (r"epic\s+games?", "epic"),
    (r"\bepic\b", "epic"),
    (r"ubisoft\s+connect", "ubisoft connect"),
    (r"\bubisoft\b", "ubisoft connect"),
    (r"pc\s+game\s+pass", "xbox"),
    (r"microsoft\s+store", "xbox"),
    (r"\bxbox\b", "xbox"),
    # battle.net: also catches "BattleNet" / "Battle Net" / "Battlenet" variants.
    (r"battle\.?\s*net", "battle.net"),
    (r"\bgog\.com\b", "gog"),
    (r"\bgog\b", "gog"),
    (r"\bea\s+app\b", "ea"),
    (r"\bea\s+games?\b", "ea"),
    (r"\bsteam\b", "steam"),
]

# Compiled once.
_COMPILED_SF: list[tuple[re.Pattern[str], str]] = [
    (re.compile(pat, re.IGNORECASE), label) for pat, label in _STOREFRONT_PATTERNS
]

# Bullet text containing these phrases is skipped — they are removals or
# editorial-only entries that have no storefront.
_SKIP_PHRASES: tuple[str, ...] = (
    "leaving",
    "removed from",
    "coming to alliance",
    "geforce now alliance",
    "free weekend",  # Temporary play access, not permanent streaming support
    "free to play this weekend",
)

# Compile regexes for meta skip phrases to avoid substring false positives
# (e.g. matching "dlc" inside "dlcs" or "adlc").
_META_SKIP_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bnew\s+dlc\b", re.IGNORECASE),
    re.compile(r"\bdlc\b", re.IGNORECASE),
    re.compile(r"\bexpansion\s+pack\b", re.IGNORECASE),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_gfn_thursday(title: str) -> bool:
    """Return True when the RSS item title looks like a GFN Thursday post."""
    low = title.lower()
    return any(sig in low for sig in GFN_TITLE_SIGNALS)


def _extract_storefronts(text: str) -> list[str]:
    """Return deduplicated canonical storefront labels found in *text*."""
    found: list[str] = []
    seen: set[str] = set()
    for pattern, label in _COMPILED_SF:
        if label not in seen and pattern.search(text):
            found.append(label)
            seen.add(label)
    return found


def _is_day_one(paren_text: str) -> bool:
    """Return True when the parenthetical metadata signals a day-one release."""
    low = paren_text.lower()
    return "new release" in low or "day one" in low or "day-one" in low


def _extract_game_title(raw_text: str) -> str | None:
    """Extract the game title from a bullet item's plain text.

    NVIDIA's canonical format is::

        Game Title (storefront, date details)

    The storefront/date metadata is ALWAYS in the LAST parenthetical block.
    The title is everything before that final block.

    Games with parentheses in their own name (e.g. "Halo (2003)", "Game (Part 1)")
    must be preserved — we must not cut at the first '(' when the game name
    itself contains parens.  We therefore find the LAST '(' that opens the final
    metadata block and treat everything before it as the game title.
    """
    # Find all opening '(' positions
    open_positions = [i for i, ch in enumerate(raw_text) if ch == "("]
    if not open_positions:
        return None
    # Walk from the last '(' backwards to find the one that corresponds to a
    # closed paren that spans to (or near) the end of the string.
    title: str | None = None
    for pos in reversed(open_positions):
        candidate_title = raw_text[:pos].strip()
        remainder = raw_text[pos:]
        # The parenthetical must close
        if ")" in remainder:
            title = candidate_title
            break
    if not title:
        return None
    # Strip known editorial suffixes appended by NVIDIA (case-insensitive)
    # Also strip dates like " — August 7" that might appear before the storefront paren
    title = re.sub(
        r"\s*[\u2013\u2014\-]\s*(RTX\s+Edition|DLSS\s+\d+.*|available\s+.*|[A-Za-z]+\s+\d+.*)$",
        "",
        title,
        flags=re.IGNORECASE,
    ).strip()
    if not title or len(title) > 120:
        return None
    return title


def _make_stable_url(game_title: str, storefront: str) -> str:
    """Return a stable synthetic URL used as the event identity key.

    The URL is the same regardless of which weekly post announced the game,
    so that monthly previews and week-of confirmations share the same key.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", game_title.lower()).strip("-")
    digest = hashlib.sha256(f"{slug}:{storefront}".encode()).hexdigest()[:12]
    return f"https://www.nvidia.com/en-us/geforce-now/games/#{digest}"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _parse_bullets(
    soup: BeautifulSoup,
    article_url: str,
    pub_date: datetime,
) -> list[NewsEvent]:
    """Extract game events from all list items in a parsed HTML body."""
    events: list[NewsEvent] = []
    seen_keys: set[str] = set()

    for li in soup.find_all("li"):
        if not isinstance(li, Tag):  # guard instead of assert — assert is stripped under -O
            continue

        # Avoid nested bullet duplication: if this <li> contains child <li>s,
        # it is a container, not a game entry. Parse only the leaf elements.
        if li.find("li") is not None:
            continue

        raw_text = li.get_text(" ", strip=True)

        # Must have at least one parenthetical section (storefront info lives there).
        paren_matches = re.findall(r"\(([^)]+)\)", raw_text)
        if not paren_matches:
            continue

        # The LAST parenthetical block is the one containing storefront + date info.
        meta_block = paren_matches[-1]

        # Skip removals and Alliance-partner entries.
        # We must NOT check the game title for these phrases to avoid false positives
        # (e.g. a game literally named "Leaving Las Vegas"). The metadata block or
        # surrounding non-title text is where these qualifiers live.
        meta_low = meta_block.lower()
        if any(phrase in meta_low for phrase in _SKIP_PHRASES):
            continue

        # Skip DLC / non-game meta blocks using strict regex boundaries.
        if any(pat.search(meta_low) for pat in _META_SKIP_PATTERNS):
            logger.debug("GFN: DLC/expansion bullet skipped: %r", raw_text[:80])
            continue

        storefronts = _extract_storefronts(meta_block)
        if not storefronts:
            # Storefront is REQUIRED — reject the entry.
            logger.debug("GFN: no storefront found in %r — skipped", raw_text[:80])
            continue

        game_title = _extract_game_title(raw_text)
        if game_title is None:
            continue

        day_one = _is_day_one(meta_block)

        for sf in storefronts:
            stable_url = _make_stable_url(game_title, sf)

            if stable_url in seen_keys:
                continue
            seen_keys.add(stable_url)

            reasons: list[str] = ["Game found in GFN Thursday bullet list"]
            score = 80
            if day_one:
                reasons.append("Day-one launch detected")
                score = 85
            reasons.append(f"Storefront explicitly mentioned: {sf}")

            metadata: dict[str, Any] = {
                "article_url": article_url,
                "original_text": raw_text,
                "storefront_raw": meta_block,
            }

            event = NewsEvent(
                source=Source.GEFORCE_NOW,
                category=Category.SUBSCRIPTION,
                promotion_type=PromotionType.GIVEAWAY,
                event_type=EventType.STREAMING_SUPPORT_ADDED,
                access_model=AccessModel.STREAMING_SUPPORT,
                ownership_model=OwnershipModel.REQUIRES_EXTERNAL_OWNERSHIP,
                title=game_title,
                url=stable_url,
                service="geforce_now",
                storefronts=[sf],
                # COLLECTOR_GUIDE §10: region must not default to global silently.
                # GFN Thursday posts reflect the NVIDIA-operated service (NA/EU).
                # Alliance-partner catalogs are deliberately not scraped unless explicitly specified.
                regions=["nvidia_operated"],
                day_one=True if day_one else None,
                confidence=Confidence(score=score, reasons=reasons),
                metadata=metadata,
            )
            events.append(event)

    return events


def _parse_feed(xml_text: str) -> list[NewsEvent]:
    """Parse an NVIDIA Blog RSS feed and return all GFN game events."""
    events: list[NewsEvent] = []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SourceError(f"GeForce NOW RSS feed parse failed: {exc}") from exc

    # RSS content:encoded namespace
    content_ns = "http://purl.org/rss/1.0/modules/content/"

    for item in root.findall(".//item"):
        title_el = item.find("title")
        if title_el is None or not title_el.text:
            continue
        post_title = title_el.text.strip()

        if not _is_gfn_thursday(post_title):
            continue

        # Prefer content:encoded, fall back to description.
        # NOTE: must use explicit `is not None` — an Element with only .text is
        # falsy in ElementTree, so bare `or` would incorrectly fall through.
        html_el = item.find(f"{{{content_ns}}}encoded")
        if html_el is None:
            html_el = item.find("description")
        if html_el is None or not html_el.text:
            continue

        link_el = item.find("link")
        article_url = (link_el.text or FEED_URL).strip() if link_el is not None else FEED_URL

        pub_date = datetime.now(UTC)
        pd_el = item.find("pubDate")
        if pd_el is not None and pd_el.text:
            try:
                pub_date = parsedate_to_datetime(pd_el.text.strip())
                if pub_date.tzinfo is None:
                    pub_date = pub_date.replace(tzinfo=UTC)
            except Exception:
                pass

        soup = BeautifulSoup(html_el.text, "html.parser")
        post_events = _parse_bullets(soup, article_url, pub_date)
        events.extend(post_events)
        logger.debug("GFN: %d events from post %r", len(post_events), post_title[:60])

    # Final deduplication across posts by stable URL (event_key already uses url).
    unique: dict[str, NewsEvent] = {}
    for ev in events:
        if ev.url not in unique:
            unique[ev.url] = ev

    return list(unique.values())


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def fetch_events() -> list[NewsEvent]:
    """Fetch and return current GFN Thursday game events.

    Raises ``SourceError`` on network or parse failures so the pipeline
    supervisor can record the outage without crashing.
    """
    try:
        xml_text = fetch_text(FEED_URL)
    except SourceError:
        raise
    except Exception as exc:
        raise SourceError(f"GeForce NOW feed fetch failed: {exc}") from exc

    return _parse_feed(xml_text)
