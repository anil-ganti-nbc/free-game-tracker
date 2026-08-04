"""Tests for the Steam deals parser (discount + review filters)."""

from __future__ import annotations

from typing import Any

from newsroom.sources import steam_deals as sd


def _special(appid: int, discount: int) -> dict[str, Any]:
    return {
        "id": appid,
        "name": f"Game {appid}",
        "discount_percent": discount,
        "original_price": 3999,
        "final_price": int(3999 * (100 - discount) / 100),
        "currency": "USD",
        "discount_expiration": 1782777600,
    }


def _featured(*items: dict[str, Any]) -> dict[str, Any]:
    return {"specials": {"items": list(items)}}


def test_candidate_specials_filters_by_discount() -> None:
    payload = _featured(
        _special(1, 10),  # too small
        _special(2, 30),  # ok (boundary)
        _special(3, 75),  # ok
        _special(4, 100),  # free -> excluded (handled elsewhere)
    )
    ids = [i["id"] for i in sd.candidate_specials(payload, min_discount=30)]
    assert ids == [2, 3]


def test_build_deal_fields() -> None:
    deal = sd.build_deal(_special(5, 40), "Very Positive", 5000, 96.0)
    assert deal is not None
    assert deal.appid == 5
    assert deal.discount_percent == 40
    assert deal.original_price == 39.99
    assert deal.final_price == 23.99
    assert deal.review_desc == "Very Positive"
    assert deal.url == "https://store.steampowered.com/app/5"
    assert deal.discount_end is not None


def test_min_reviews_and_tier_are_enforced_by_helpers() -> None:
    # These are the two gates _evaluate applies; verify the shared helpers.
    from newsroom.sources.steam_breakouts import tier_meets

    assert tier_meets("Mixed", "Mixed") is True
    assert tier_meets("Mostly Positive", "Mixed") is True
    assert tier_meets("Mostly Negative", "Mixed") is False
