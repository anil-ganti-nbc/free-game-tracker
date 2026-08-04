"""GOG sensor — paid games that are currently free (giveaways).

GOG's catalog API lists products with a base price and a final price. A giveaway
shows up as a normally-paid game whose final price has dropped to zero. That is
exactly the rule we apply: keep products where the base price is above zero and
the final price is zero. Free-to-play titles and demos have a base price of zero
and are therefore excluded — which is what keeps us off the F2P games the scope
tells us to ignore.

The catalog does not expose a promotion end date, so GOG detections carry a
reduced confidence with that reason attached.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from newsroom.models import Confidence, NewsEvent, PromotionType, Source
from newsroom.sources._http import fetch_json

logger = logging.getLogger(__name__)

GOG_FREE_GAMES_URL = (
    "https://catalog.gog.com/v1/catalog"
    "?limit=48&price=between:0,0&order=desc:trending&productType=in:game"
    "&countryCode=US&currencyCode=USD&locale=en-US&page=1"
)
_STORE_GAME_BASE = "https://www.gog.com/en/game/"


def parse_free_games(payload: dict[str, Any]) -> list[NewsEvent]:
    """Convert a GOG catalog payload into ``NewsEvent`` objects.

    Only paid games that are currently free are returned. Malformed products are
    skipped with a warning rather than failing the whole parse.
    """
    products = payload.get("products") or []
    events: list[NewsEvent] = []
    for product in products:
        try:
            event = _normalize_product(product)
        except Exception:  # noqa: BLE001 - one bad product must not fail the run
            logger.warning(
                "Skipping unparseable GOG product %r", product.get("title"), exc_info=True
            )
            continue
        if event is not None:
            events.append(event)
    return events


def _normalize_product(product: dict[str, Any]) -> NewsEvent | None:
    """Turn one product into a ``NewsEvent``, or ``None`` if it is not a giveaway."""
    price = product.get("price") or {}
    base = _amount((price.get("baseMoney") or {}).get("amount"))
    final = _amount((price.get("finalMoney") or {}).get("amount"))

    # A giveaway = a paid game now free. Excludes F2P/demos (base price of 0).
    if base is None or final is None or base <= 0 or final != 0:
        return None

    title = product.get("title")
    if not title:
        return None

    slug = product.get("slug", "")
    url = product.get("storeLink") or f"{_STORE_GAME_BASE}{slug}"
    developer = _first(product.get("developers"))
    publisher = _first(product.get("publishers"))

    return NewsEvent(
        source=Source.GOG,
        title=str(title),
        url=str(url),
        developer=developer,
        publisher=publisher,
        promotion_type=PromotionType.GIVEAWAY,
        original_price=base,
        current_price=0.0,
        promotion_end=None,  # Not exposed by the catalog.
        confidence=_score(original_price=base),
        metadata={"gog_id": product.get("id")},
    )


def _amount(value: Any) -> float | None:
    """Parse GOG's string money amount (e.g. "9.99") into a float, or ``None``."""
    if value is None:
        return None
    try:
        return float(round(float(value), 2))
    except (ValueError, TypeError):
        return None


def _first(values: Any) -> str | None:
    """Return the first entry of a list as a string, or ``None`` if empty."""
    if isinstance(values, list) and values:
        return str(values[0])
    return None


def _score(*, original_price: float) -> Confidence:
    """Confidence for a GOG giveaway. Always missing an end date from the catalog."""
    return Confidence(
        score=70,
        reasons=[
            "GOG price dropped from paid to free",
            f"MSRP present ({original_price:.2f})",
            "Promotion end date unavailable",
        ],
    )


def fetch_free_games(client: httpx.Client | None = None) -> list[NewsEvent]:
    """Fetch GOG's free games and return giveaways as events.

    Raises:
        SourceError: If the endpoint cannot be fetched after all retries.
    """
    payload = fetch_json(GOG_FREE_GAMES_URL, client=client)
    events = parse_free_games(payload)
    logger.info("GOG: %d giveaway(s) detected", len(events))
    return events
