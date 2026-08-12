import logging
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

PLAYSTATION_BLOG_TZ = ZoneInfo("America/Los_Angeles")

from bs4 import BeautifulSoup

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

US_BLOG_FEED = "https://blog.playstation.com/category/ps-plus/feed/"
#: The ps-plus category feed only ever contains the monthly roundup posts —
#: a same-day standalone article about one game (e.g. "X joins the PS Plus
#: Game Catalog today") is never one of its own items, only a link inside a
#: roundup's body. The general site feed does carry standalone posts as their
#: own items, so it is scanned too (see _detect_standalone_access_event).
GENERAL_BLOG_FEED = "https://blog.playstation.com/feed/"

MONTHS = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]
MONTH_PATTERN = r"(?:" + "|".join(MONTHS) + r")"


def parse_month_day(text: str) -> tuple[int, int] | None:
    m = re.search(r"(" + MONTH_PATTERN + r")\s+(\d{1,2})", text.lower())
    if not m:
        return None
    month_str = m.group(1)
    day = int(m.group(2))
    month = MONTHS.index(month_str) + 1
    return month, day


def _parse_dates_from_text(
    text: str, pub_date: datetime
) -> tuple[datetime | None, datetime | None, str | None]:
    text_lower = text.lower()
    start = None
    end = None
    phrase = None

    if "available today" in text_lower:
        pub_pt = pub_date.astimezone(PLAYSTATION_BLOG_TZ)
        start = datetime(pub_pt.year, pub_pt.month, pub_pt.day, tzinfo=UTC)
        phrase = "available today"

    elif "available next tuesday" in text_lower:
        pub_pt = pub_date.astimezone(PLAYSTATION_BLOG_TZ)
        days_ahead = 1 - pub_pt.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        target_pt = pub_pt + timedelta(days=days_ahead)
        start = datetime(target_pt.year, target_pt.month, target_pt.day, tzinfo=UTC)
        phrase = "available next tuesday"

    else:
        # Check "available from X until Y"
        m = re.search(
            r"from.*?("
            + MONTH_PATTERN
            + r"\s+\d{1,2}).*?until.*?("
            + MONTH_PATTERN
            + r"\s+\d{1,2})",
            text_lower,
        )
        if m:
            s_month, s_day = parse_month_day(str(m.group(1))) or (0, 0)
            e_month, e_day = parse_month_day(str(m.group(2))) or (0, 0)
            if s_month and e_month:
                s_year = pub_date.year
                e_year = pub_date.year
                if s_month == 12 and e_month == 1:
                    e_year += 1
                elif s_month < pub_date.month and pub_date.month >= 11:
                    s_year += 1
                    e_year += 1

                start = datetime(s_year, s_month, s_day, tzinfo=UTC)
                end = datetime(e_year, e_month, e_day, tzinfo=UTC)
                phrase = m.group(0)

        # Check "claim by X"
        elif "claim by " in text_lower:
            m = re.search(r"claim by.*?(" + MONTH_PATTERN + r"\s+\d{1,2})", text_lower)
            if m:
                e_month, e_day = parse_month_day(str(m.group(1))) or (0, 0)
                if e_month:
                    e_year = pub_date.year
                    if e_month < pub_date.month and pub_date.month >= 11:
                        e_year += 1
                    end = datetime(e_year, e_month, e_day, tzinfo=UTC)
                    phrase = m.group(0)

        # Check general "available X" / "available on X" / "available from X"
        if not start and not end:
            matches_iter = filter(
                None,
                [
                    re.search(
                        r"(?:available|joining the catalog).*?(" + MONTH_PATTERN + r"\s+\d{1,2})",
                        text_lower,
                    ),
                    re.search(r"available from.*?(" + MONTH_PATTERN + r"\s+\d{1,2})", text_lower),
                ],
            )
            matches_list = list(matches_iter)
            if matches_list:
                m_match = matches_list[0]
                s_month, s_day = parse_month_day(str(m_match.group(1))) or (0, 0)
                if s_month:
                    s_year = pub_date.year
                    if s_month < pub_date.month and pub_date.month >= 11:
                        s_year += 1
                    start = datetime(s_year, s_month, s_day, tzinfo=UTC)
                    phrase = m_match.group(0)

    return start, end, phrase


def _extract_games_from_html(
    html_content: str,
    section_tiers: list[str],
    event_type: EventType,
    access_model: AccessModel,
    ownership_model: OwnershipModel,
    pub_date: datetime,
    source_url: str,
) -> list[NewsEvent]:
    events = []
    soup = BeautifulSoup(html_content, "html.parser")

    # 1. Article-level dates
    art_start, art_end, art_phrase = None, None, None

    current_tiers = section_tiers[:]
    current_metadata: dict[str, Any] = {}

    sec_start, sec_end, sec_phrase = None, None, None
    has_seen_section = False

    for elem in soup.find_all(["p", "h2", "h3", "h4", "ul", "li", "strong"]):
        text = elem.get_text(" ", strip=True)
        low_text = text.lower()

        # Is it a heading?
        if elem.name in ["h2", "h3", "h4"]:
            is_section = False
            if (
                "playstation plus extra and premium" in low_text
                or "playstation plus extra" in low_text
            ):
                current_tiers = ["extra", "premium"]
                current_metadata = {}
                sec_start, sec_end, sec_phrase = None, None, None
                is_section = True
                has_seen_section = True
            elif "playstation plus premium" in low_text:
                current_tiers = ["premium"]
                current_metadata = {"catalog_section": "classics"} if "classics" in low_text else {}
                sec_start, sec_end, sec_phrase = None, None, None
                is_section = True
                has_seen_section = True
            elif "deluxe" in low_text and "deluxe" not in current_tiers:
                current_tiers.append("deluxe")
                is_section = True
                has_seen_section = True

            # If it has dates itself
            ds, de, dp = _parse_dates_from_text(text, pub_date)
            if ds or de:
                sec_start, sec_end, sec_phrase = ds, de, dp

            if is_section:
                continue

        # If it's a paragraph or list item, it could just be date text
        if elem.name in ["p", "li"] and not elem.find("strong"):
            ds, de, dp = _parse_dates_from_text(text, pub_date)
            if ds or de:
                sec_start, sec_end, sec_phrase = ds, de, dp
                if not has_seen_section:
                    art_start, art_end, art_phrase = ds, de, dp

        # Game parsing
        if "|" in text and ("PS4" in text or "PS5" in text or "PS VR2" in text):
            # Make sure it's not a section header
            if not (
                "playstation plus premium" in low_text
                or "playstation plus extra" in low_text
                or "deluxe" in low_text
            ):
                parts = [p.strip() for p in text.split("|")]
                if len(parts) >= 2:
                    title = parts[0]
                    platforms_raw = parts[-1]
                    platforms = []
                    if "PS4" in platforms_raw:
                        platforms.append("ps4")
                    if "PS5" in platforms_raw:
                        platforms.append("ps5")
                    if "PS VR2" in platforms_raw:
                        platforms.append("ps_vr2")

                    # Hierarchy: Game specific -> Enclosing elem -> Section -> Article
                    g_start, g_end, g_phrase = None, None, None
                    parent = elem.parent
                    if parent and (
                        parent.name == "p" or parent.name == "li" or parent.name in ["h2", "h3"]
                    ):
                        p_text = parent.get_text(" ", strip=True)
                        g_start, g_end, g_phrase = _parse_dates_from_text(p_text, pub_date)

                    # Also check if it's the element itself that contains the date
                    ds, de, dp = _parse_dates_from_text(text, pub_date)
                    if ds or de:
                        g_start, g_end, g_phrase = ds, de, dp

                    final_start = g_start or sec_start or art_start
                    final_end = g_end or sec_end or art_end
                    final_phrase = g_phrase or sec_phrase or art_phrase

                    # For catalog additions, end dates aren't claim deadlines usually
                    claim_deadline = final_end if event_type == EventType.CLAIMABLE_GAME else None

                    reasons = [
                        "Official PlayStation Blog format detected",
                        f"Explicit title and platform: {text}",
                    ]
                    metadata = {"raw_blog_text": text, **current_metadata}
                    if final_phrase:
                        metadata["date_phrase"] = final_phrase

                    if final_start or claim_deadline:
                        reasons.append("Dates successfully bound by context")
                    else:
                        metadata["unresolved_dates"] = True

                    events.append(
                        NewsEvent(
                            source=Source.PLAYSTATION_PLUS,
                            category=Category.SUBSCRIPTION,
                            promotion_type=PromotionType.GIVEAWAY,
                            event_type=event_type,
                            access_model=access_model,
                            ownership_model=ownership_model,
                            title=title,
                            url=source_url,
                            service="playstation_plus",
                            tiers=current_tiers,
                            platforms=platforms,
                            regions=["global"],
                            available_from=final_start,
                            claim_deadline=claim_deadline,
                            confidence=Confidence(
                                score=95
                                if (platforms and current_tiers and (final_start or claim_deadline))
                                else 70,
                                reasons=reasons,
                            ),
                            metadata=metadata,
                        )
                    )

    return events


# --- Standalone (non-roundup) article detection -----------------------------
#
# A monthly "Game Catalog"/"Monthly Games" roundup is the reliable, structured
# case _extract_games_from_html already handles well. But Sony also publishes
# same-day standalone articles about a single game — primarily about an update,
# a launch, or the game itself — that happen to also announce a new PS Plus
# access event in passing (the Helldivers 2 "Devoid of Liberty" incident: the
# article is almost entirely patch notes, with two sentences announcing the
# PS Plus Game Catalog addition). Those articles' *headlines* don't reliably
# contain "game catalog"/"monthly games", so they must be recognised from
# content, not title keywords. This intentionally does not attempt catalogue
# *removals* or "material changes to previously announced availability" —
# those remain the documented, pre-existing limitation in
# docs/PLAYSTATION_PLUS_COLLECTOR.md.

#: A concrete claim that a *specific* game gained subscription access, not
#: just a mention of PlayStation Plus somewhere in the text. Captures the
#: leading capitalized phrase as the game name.
_ACCESS_EVENT_RE = re.compile(
    r"(?P<subject>[A-Z][\w'’:\-]*(?:\s+[A-Z0-9][\w'’:\-]*){0,5})"
    r"(?:\s+(?:also|now|soon|too))?\s+"
    r"(?:joins|is joining|enters|entering|arrives?\s+in|comes?\s+to|"
    r"will\s+be\s+added\s+to|is\s+now\s+(?:available|part\s+of)|"
    r"will\s+be\s+available\s+(?:to|on|in)|becomes?\s+available\s+(?:to|on|in))"
    r"(?:(?!\.).){0,60}?"
    r"(?:playstation\s+plus|game\s+catalog)",
    re.I,
)

#: Casual mentions that must not, by themselves, trigger a detection — a
#: requirement, a discount, or a passing reference is not a new access event.
_ACCESS_EVENT_EXCLUSIONS = [
    "requires playstation plus",
    "playstation plus is required",
    "playstation plus subscription required",
    "playstation plus discount",
    "discount for playstation plus",
    "playstation plus members save",
    "playstation plus members can save",
]

_TIER_PHRASES = [
    (("extra and premium",), ["extra", "premium"]),
    (("extra & premium",), ["extra", "premium"]),
    (("extra",), ["extra"]),
    (("premium",), ["premium"]),
    (("essential",), ["essential"]),
]


def _detect_tiers(text: str) -> list[str]:
    low = text.lower()
    for phrases, tiers in _TIER_PHRASES:
        if any(p in low for p in phrases) and "playstation plus" in low:
            return tiers
    return []


def _is_monthly_claim(text: str) -> bool:
    low = text.lower()
    return "monthly game" in low or "essential" in low


def _detect_standalone_access_event(
    title: str,
    html_content: str,
    pub_date: datetime,
    source_url: str,
) -> NewsEvent | None:
    """Recognise a standalone article announcing one game's new PS Plus access.

    Scans paragraph-by-paragraph (not just the headline) for a sentence of the
    shape "<Game> joins/enters/arrives in ... PlayStation Plus / Game Catalog",
    rejecting casual mentions (requirements, discounts). Reuses the same
    date-context parser and tier vocabulary as the roundup path so a detection
    here produces an event indistinguishable in shape from one the roundup
    parser would have produced for the same game.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    blocks = [title] + [
        el.get_text(" ", strip=True) for el in soup.find_all(["p", "h2", "h3", "li"])
    ]

    for text in blocks:
        if not text or "playstation plus" not in text.lower():
            continue
        low_text = text.lower()
        if any(phrase in low_text for phrase in _ACCESS_EVENT_EXCLUSIONS):
            continue

        match = _ACCESS_EVENT_RE.search(text)
        if not match:
            continue

        subject = match.group("subject").strip()
        if subject.lower() in {"it", "this", "these", "they", "today"}:
            continue

        tiers = _detect_tiers(text) or _detect_tiers(" ".join(blocks))
        if not tiers:
            continue  # Can't tell what tier grants access; don't guess.

        is_monthly = _is_monthly_claim(text) or _is_monthly_claim(title)
        event_type = EventType.CLAIMABLE_GAME if is_monthly else EventType.CATALOG_ADDITION
        access_model = AccessModel.CLAIMABLE if is_monthly else AccessModel.SUBSCRIPTION_CATALOG
        ownership_model = (
            OwnershipModel.PERMANENT_WHILE_ACCOUNT_EXISTS
            if is_monthly
            else OwnershipModel.ACCESSIBLE_WHILE_IN_CATALOG
        )

        start, end, phrase = _parse_dates_from_text(text, pub_date)
        if not start and "today" in low_text:
            pub_pt = pub_date.astimezone(PLAYSTATION_BLOG_TZ)
            start = datetime(pub_pt.year, pub_pt.month, pub_pt.day, tzinfo=UTC)
            phrase = phrase or "today (standalone article, no explicit date)"

        reasons = [
            "Standalone (non-roundup) article content matched an access-change pattern",
            f"Matched sentence: {text[:200]}",
        ]
        metadata: dict[str, Any] = {"raw_blog_text": text, "standalone_detection": True}
        if phrase:
            metadata["date_phrase"] = phrase
        if start:
            reasons.append("Date resolved from article content")
        else:
            metadata["unresolved_dates"] = True

        claim_deadline = end if event_type == EventType.CLAIMABLE_GAME else None

        return NewsEvent(
            source=Source.PLAYSTATION_PLUS,
            category=Category.SUBSCRIPTION,
            promotion_type=PromotionType.GIVEAWAY,
            event_type=event_type,
            access_model=access_model,
            ownership_model=ownership_model,
            title=subject,
            url=source_url,
            service="playstation_plus",
            tiers=tiers,
            regions=["global"],
            available_from=start,
            claim_deadline=claim_deadline,
            confidence=Confidence(score=70 if start else 55, reasons=reasons),
            metadata=metadata,
        )

    return None


def _parse_feed_candidates(xml_text: str, feed_url: str) -> dict[str, dict[str, Any]]:
    """Parse one RSS feed into {link: {title, pub_date, item}}, newest-safe.

    Items with a missing/unparseable pubDate or link are dropped (logged) —
    they can't be horizon-filtered or deduplicated reliably.
    """
    import email.utils

    candidates: dict[str, dict[str, Any]] = {}
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.error(f"PlayStation Blog feed malformed ({feed_url}): {e}")
        return candidates

    for item in root.findall(".//item"):
        title_el = item.find("title")
        if title_el is None or not title_el.text:
            continue
        title = title_el.text

        link_el = item.find("link")
        link = link_el.text if link_el is not None and link_el.text else None
        if not link:
            continue

        pubDate_el = item.find("pubDate")
        pub_date_str = pubDate_el.text if (pubDate_el is not None and pubDate_el.text) else ""
        pub_date = None
        if pub_date_str:
            try:
                parsed = email.utils.parsedate_to_datetime(pub_date_str)
                if parsed:
                    pub_date = parsed.astimezone(UTC)
            except Exception as e:
                logger.error(f"Malformed pubDate for item '{title}': {e}")

        if not pub_date:
            logger.error(
                f"Missing or malformed pubDate for '{title}', degradation applied (skipped)."
            )
            continue

        candidates[link] = {"title": title, "pub_date": pub_date, "item": item}

    return candidates


def fetch_events() -> list[NewsEvent]:
    events: list[NewsEvent] = []

    # Poll both feeds, fault-isolated: one feed failing (network, malformed
    # XML) must not lose candidates the other feed still has. Merge by link so
    # an article present in both (a roundup often is) is only processed once.
    candidates_by_link: dict[str, dict[str, Any]] = {}
    for feed_url in (US_BLOG_FEED, GENERAL_BLOG_FEED):
        try:
            xml_text = fetch_text(feed_url)
        except SourceError as e:
            logger.error(f"PlayStation Blog fetch failed ({feed_url}): {e}")
            continue
        for link, candidate in _parse_feed_candidates(xml_text, feed_url).items():
            candidates_by_link.setdefault(link, candidate)

    # Sort newest first
    candidates = sorted(candidates_by_link.values(), key=lambda x: x["pub_date"], reverse=True)

    # Apply discovery horizon
    now = datetime.now(UTC)
    horizon_days = 90
    within_horizon = [c for c in candidates if (now - c["pub_date"]).days <= horizon_days]

    # Two feeds, each capped at ~10 items by PlayStation Blog itself: bounded
    # and cheap (no extra network calls — content is already embedded), so
    # every non-roundup candidate is still worth inspecting for an embedded
    # access-change event rather than discarded by its headline alone.
    for c in within_horizon[:20]:
        title = c["title"]
        pub_date = c["pub_date"]
        item = c["item"]

        content_el = item.find("{http://purl.org/rss/1.0/modules/content/}encoded")
        if content_el is None or not content_el.text:
            continue
        html_content = content_el.text

        link_el = item.find("link")
        source_url = link_el.text if link_el is not None and link_el.text else US_BLOG_FEED

        low_t = title.lower()
        if "monthly games" in low_t or "games for" in low_t:
            events.extend(
                _extract_games_from_html(
                    html_content,
                    section_tiers=["essential"],
                    event_type=EventType.CLAIMABLE_GAME,
                    access_model=AccessModel.CLAIMABLE,
                    ownership_model=OwnershipModel.PERMANENT_WHILE_ACCOUNT_EXISTS,
                    pub_date=pub_date,
                    source_url=source_url,
                )
            )
        elif "game catalog" in low_t:
            events.extend(
                _extract_games_from_html(
                    html_content,
                    section_tiers=["extra", "premium"],
                    event_type=EventType.CATALOG_ADDITION,
                    access_model=AccessModel.SUBSCRIPTION_CATALOG,
                    ownership_model=OwnershipModel.ACCESSIBLE_WHILE_IN_CATALOG,
                    pub_date=pub_date,
                    source_url=source_url,
                )
            )
        else:
            standalone = _detect_standalone_access_event(title, html_content, pub_date, source_url)
            if standalone is not None:
                events.append(standalone)

    # A same-day standalone article can describe the exact game/tier/date a
    # roundup article already covers (this is what happened with Helldivers 2:
    # both the August roundup and its own standalone article shipped the same
    # day). Collapse those to one event — by content, not URL, since the two
    # articles have different URLs — preferring the higher-confidence one.
    def _content_key(e: NewsEvent) -> tuple[Any, ...]:
        return (
            e.event_type,
            e.service,
            e.title.strip().lower(),
            tuple(sorted(e.tiers)),
            e.available_from,
        )

    by_content: dict[tuple[Any, ...], NewsEvent] = {}
    for e in events:
        key = _content_key(e)
        existing = by_content.get(key)
        if existing is None or e.confidence.score > existing.confidence.score:
            by_content[key] = e
    events = list(by_content.values())

    unique_events = {}
    for e in events:
        if e.event_key not in unique_events or (
            e.available_from and not unique_events[e.event_key].available_from
        ):
            unique_events[e.event_key] = e

    return list(unique_events.values())
