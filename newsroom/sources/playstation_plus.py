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


def fetch_events() -> list[NewsEvent]:
    events: list[NewsEvent] = []
    try:
        xml_text = fetch_text(US_BLOG_FEED)
    except SourceError as e:
        logger.error(f"PlayStation Blog fetch failed: {e}")
        return []

    root = ET.fromstring(xml_text)

    # 1. Parse all candidate pubDates
    candidates = []
    import email.utils

    for item in root.findall(".//item"):
        title_el = item.find("title")
        if title_el is None or not title_el.text:
            continue
        title = title_el.text

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

        candidates.append({"title": title, "pub_date": pub_date, "item": item})

    # 2. Sort newest first
    candidates.sort(key=lambda x: x["pub_date"], reverse=True)

    # 3. Filter by relevance
    relevant = []

    TITLE_VARIANTS = ["monthly games", "game catalog", "games for"]
    for c in candidates:
        low_t = c["title"].lower()
        if any(v in low_t for v in TITLE_VARIANTS):
            relevant.append(c)

    # 4. Apply discovery horizon (e.g. 60 days)
    now = datetime.now(UTC)
    horizon_days = 90
    within_horizon = []
    for c in relevant:
        if (now - c["pub_date"]).days <= horizon_days:
            within_horizon.append(c)

    # 5. Fetch/parse articles (Apply a safety item limit here if needed, but not before sorting!)
    # We will parse up to 5 relevant recent articles to avoid infinite loops, but realistically RSS has 10.
    for c in within_horizon[:10]:
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

    unique_events = {}
    for e in events:
        if e.event_key not in unique_events or (
            e.available_from and not unique_events[e.event_key].available_from
        ):
            unique_events[e.event_key] = e

    return list(unique_events.values())
