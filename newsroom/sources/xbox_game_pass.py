import logging
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from typing import Any

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

FEED_URL = "https://news.xbox.com/en-us/feed/"

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


def _parse_date_from_text(text: str, pub_date: datetime) -> datetime | None:
    text_lower = text.lower()
    m = filter(
        None,
        [
            re.search(r"–?\s*(" + MONTH_PATTERN + r"\s+\d{1,2})", text_lower),
            re.search(r"coming\s+(" + MONTH_PATTERN + r"\s+\d{1,2})", text_lower),
            re.search(r"leaving\s+(" + MONTH_PATTERN + r"\s+\d{1,2})", text_lower),
        ],
    )
    matched = list(m)
    date_val = None
    if matched:
        month, day = parse_month_day(matched[0].group(1)) or (0, 0)
        if month:
            year = pub_date.year
            if month < pub_date.month and pub_date.month >= 11:
                year += 1
            date_val = datetime(year, month, day, tzinfo=UTC)

    if "available today" in text_lower or "available now" in text_lower:
        date_val = pub_date

    return date_val


def _parse_platforms(text: str) -> list[str]:
    low = text.lower()
    plats = []
    if "cloud" in low:
        plats.append("cloud")
    if "console" in low:
        plats.append("console")
    if "xbox one" in low:
        plats.append("xbox_one")
    if "xbox series" in low:
        plats.append("xbox_series")
    if "pc" in low and (
        "pc game pass" not in low
        or "and pc" in low
        or "(pc" in low
        or " pc" in low
        or " pc)" in low
    ):
        if re.search(r"\bpc\b", low.replace("pc game pass", "")):
            plats.append("pc")
    if "handheld" in low:
        plats.append("handheld")
    return sorted(list(set(plats)))


def _parse_plans(text: str) -> tuple[list[str], list[str]]:
    low = text.lower()
    plans = set()
    raws = set()

    if "ultimate" in low:
        plans.add("ultimate")
        raws.add("ultimate")

    if "premium" in low:
        plans.add("premium")
        raws.add("premium")
    elif "standard" in low:
        plans.add("premium")
        raws.add("standard")

    if "essential" in low:
        plans.add("essential")
        raws.add("essential")
    elif "core" in low:
        plans.add("essential")
        raws.add("core")

    if "pc game pass" in low or "pc only" in low:
        plans.add("pc_game_pass")
        if "pc game pass" in low:
            raws.add("pc game pass")
        if "pc only" in low:
            raws.add("pc only")

    if "xbox game pass for console" in low:
        plans.add("premium")
        raws.add("game pass for console")

    return sorted(list(plans)), sorted(list(raws))


def _extract_from_post(
    html_content: str, pub_date: datetime, source_url: str, post_title: str
) -> list[NewsEvent]:
    events = []
    soup = BeautifulSoup(html_content, "html.parser")

    current_section = None
    section_date = None

    blocked_sections = [
        "in-case you missed it",
        "in case you missed it",
        "in-game benefits",
        "dlc",
        "updates",
        "game updates",
        "perks",
    ]

    for elem in soup.find_all(["h2", "h3", "p", "li"]):
        text = elem.get_text(" ", strip=True)
        if not text:
            continue
        low = text.lower()

        if elem.name in ["h2", "h3"]:
            current_section = low
            section_date = None  # Reset section state explicitly
            if "leaving" in low:
                sd = _parse_date_from_text(low, pub_date)
                if sd:
                    section_date = sd
            continue

        if current_section and any(b in current_section for b in blocked_sections):
            continue

        # Look for typical game entries: "Title (Platforms) - Date"
        if " (" in text and ")" in text:
            # We strictly bind next-sibling inspection to valid structural sibling.

            title_part = text.split(" (")[0].strip()
            if len(title_part) > 100 or len(title_part) == 0:
                continue

            platforms = _parse_platforms(text)
            if not platforms:
                continue

            g_date = _parse_date_from_text(text, pub_date)
            plans, raw_plans = _parse_plans(text)

            next_text = ""
            nxt = elem.find_next_sibling(["p", "li"])
            if nxt:
                test_nxt = nxt.get_text(" ", strip=True)
                test_low = test_nxt.lower()
                # Stricter sibling inclusion context (must mention game pass or plans)
                if (
                    "game pass" in test_low
                    or "ultimate" in test_low
                    or "premium" in test_low
                    or "essential" in test_low
                    or "pc only" in test_low
                ):
                    next_text = test_nxt
                    nxt_plans, nxt_raw_plans = _parse_plans(next_text)
                    plans = sorted(list(set(plans + nxt_plans)))
                    raw_plans = sorted(list(set(raw_plans + nxt_raw_plans)))
                    if not g_date:
                        g_date = _parse_date_from_text(next_text, pub_date)

            is_leaving = current_section and "leaving" in current_section
            event_type = EventType.CATALOG_REMOVAL if is_leaving else EventType.CATALOG_ADDITION

            final_date = g_date or section_date
            if (
                not final_date
                and not is_leaving
                and current_section
                and ("available today" in current_section or "available now" in current_section)
            ):
                final_date = pub_date

            day_one = "day one" in low or "day one" in next_text.lower() or "day-one" in low
            ea_play = "ea play" in low or "ea play" in next_text.lower()

            metadata: dict[str, Any] = {
                "raw_platforms": text,
                "raw_plans": raw_plans,
            }
            if ea_play:
                metadata["ea_play"] = True

            reasons = ["Parsed from official Xbox Wire article."]
            conf = 90

            if not plans and not is_leaving:
                conf -= 30
                reasons.append("Unknown plan eligibility.")
            if is_leaving and not final_date:
                conf -= 20
                reasons.append("Leaving soon without explicit removal date.")

            evt = NewsEvent(
                source=Source.XBOX_GAME_PASS,
                category=Category.SUBSCRIPTION,
                promotion_type=PromotionType.GIVEAWAY,
                event_type=event_type,
                access_model=AccessModel.SUBSCRIPTION_CATALOG,
                ownership_model=OwnershipModel.ACCESSIBLE_WHILE_IN_CATALOG,
                title=title_part,
                url=source_url,
                service="xbox_game_pass",
                tiers=plans,
                platforms=platforms,
                regions=["US"],  # Fix region semantics from global
                available_from=final_date if not is_leaving else None,
                available_until=final_date if is_leaving else None,
                day_one=True if day_one else None,
                confidence=Confidence(score=max(0, conf), reasons=reasons),
                metadata=metadata,
            )
            events.append(evt)

    return events


def fetch_events() -> list[NewsEvent]:
    events: list[NewsEvent] = []

    try:
        xml_text = fetch_text(FEED_URL)
    except Exception as e:
        # Wrap everything in SourceError for the pipeline supervisor
        raise SourceError(f"Xbox Game Pass fetch failed: {e}") from e

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise SourceError(f"Failed to parse Xbox Wire XML: {e}") from e

    for item in root.findall(".//item"):
        title_el = item.find("title")
        if title_el is None or not title_el.text:
            continue
        title = title_el.text
        title_low = title.lower()

        # Robust title matching
        if not ("game pass" in title_low or "coming to xbox" in title_low):
            continue

        content_el = item.find("{http://purl.org/rss/1.0/modules/content/}encoded")
        if content_el is None or not content_el.text:
            continue
        html_content = content_el.text

        # Secondary check for article body
        if "game pass" not in html_content.lower():
            continue

        link_el = item.find("link")
        source_url = link_el.text if link_el is not None and link_el.text else FEED_URL

        pubDate_el = item.find("pubDate")
        pub_date_str = pubDate_el.text or "" if pubDate_el is not None else ""
        pub_date = datetime.now(UTC)
        try:
            import email.utils

            parsed = email.utils.parsedate_to_datetime(pub_date_str)
            if parsed:
                pub_date = parsed.astimezone(UTC)
        except Exception:
            pass

        # Time-window relevance rule: ignore posts older than 30 days
        from datetime import timedelta

        if pub_date < datetime.now(UTC) - timedelta(days=30):
            continue

        try:
            post_evs = _extract_from_post(html_content, pub_date, source_url, title)
            events.extend(post_evs)
        except Exception as e:
            logger.warning("Error extracting from %s: %s", source_url, e)

    unique_events = {e.event_key: e for e in events}

    return list(unique_events.values())
