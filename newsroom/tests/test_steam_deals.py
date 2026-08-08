"""Tests for the Steam deals parser (discount + review filters).

Also guards against the "Gears 5" miss: the old source (Steam's featured
``specials`` carousel) is hard-capped at 10 curated items and never surfaced
most real discounts. These tests cover the replacement (a paged, review-sorted
scan of Steam's specials search) so that class of discovery gap can't recur
silently — a well-reviewed, deeply-discounted game must be found even when it
isn't in a small handful of "front page" picks, and a source-level failure
must be visible rather than swallowed as an empty result.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from newsroom.sources import steam_deals as sd
from newsroom.sources._http import SourceError


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


def _search_row(appid: int, name: str, discount: int, original: str, final: str) -> str:
    """One result row, shaped like Steam's real search/results HTML."""
    return f"""
    <a href="https://store.steampowered.com/app/{appid}/{name}/"
       data-ds-appid="{appid}" data-ds-itemkey="App_{appid}" class="search_result_row">
        <div class="responsive_search_name_combined">
            <div class="search_name ellipsis"><span class="title">{name}</span></div>
            <div class="search_price_discount_combined responsive_secondrow">
                <div class="discount_block search_discount_block" data-discount="{discount}">
                    <div class="discount_pct">-{discount}%</div>
                    <div class="discount_prices">
                        <div class="discount_original_price">${original}</div>
                        <div class="discount_final_price">${final}</div>
                    </div>
                </div>
            </div>
        </div>
    </a>
    """


def _search_page(*rows: tuple[int, str, int, str, str]) -> str:
    return "<!-- List Items -->\n" + "\n".join(_search_row(*r) for r in rows)


def test_candidate_specials_filters_by_discount() -> None:
    items = [
        _special(1, 10),  # too small
        _special(2, 30),  # ok (boundary)
        _special(3, 75),  # ok
        _special(4, 100),  # free -> excluded (handled elsewhere)
    ]
    ids = [i["id"] for i in sd.candidate_specials(items, min_discount=30)]
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


def test_parse_search_page_reads_real_row_shape() -> None:
    """A Gears-5-shaped row: old game, heavily discounted, well reviewed."""
    html = _search_page((1097840, "Gears 5", 85, "29.99", "4.49"))
    items = sd.parse_search_page(html)
    assert items == [
        {
            "id": 1097840,
            "name": "Gears 5",
            "discount_percent": 85,
            "original_price": 2999,
            "final_price": 449,
            "discount_expiration": None,
        }
    ]


def test_parse_search_page_handles_multiple_rows() -> None:
    html = _search_page(
        (10, "Game Ten", 30, "19.99", "13.99"),
        (20, "Game Twenty", 60, "9.99", "3.99"),
    )
    items = sd.parse_search_page(html)
    assert [i["id"] for i in items] == [10, 20]
    assert [i["discount_percent"] for i in items] == [30, 60]


def test_parse_search_page_ignores_rows_without_a_discount_block() -> None:
    # A full-price row in the same markup family (no discount block at all).
    html = """<a data-ds-appid="99" class="search_result_row">
        <span class="title">Full Price Game</span>
    </a>"""
    assert sd.parse_search_page(html) == []


def test_fetch_deals_finds_a_deep_candidate_beyond_a_ten_item_horizon(monkeypatch: pytest.MonkeyPatch) -> None:
    """The regression case: a game that would never appear in a 10-item feed.

    Simulates a target (Gears-5-shaped: old, high discount, well reviewed)
    sitting on page 3 of a review-sorted scan — well past where the old
    10-item featured carousel would ever look — and asserts it is still
    discovered once the horizon is widened to cover multiple pages.
    """
    pages = {
        0: sd.parse_search_page(_search_page(*[(1000 + i, f"Filler {i}", 40, "19.99", "11.99") for i in range(100)])),
        1: sd.parse_search_page(_search_page(*[(2000 + i, f"Filler {i}", 40, "19.99", "11.99") for i in range(100)])),
        2: sd.parse_search_page(_search_page((1097840, "Gears 5", 85, "29.99", "4.49"))),
    }
    calls: list[str] = []

    def fake_fetch_json(url: str, *, client: httpx.Client | None = None, headers: Any = None) -> dict[str, Any]:
        calls.append(url)
        start = int(url.split("start=")[1].split("&")[0])
        page = start // sd._SEARCH_PAGE_SIZE
        rows = pages.get(page, [])
        # Re-render minimal html isn't needed: fetch_deals expects a "results_html"
        # payload, so hand back pre-rendered HTML matching the parsed rows.
        html = _search_page(
            *[(r["id"], r["name"], r["discount_percent"], "0.00", "0.00") for r in rows]
        )
        return {"results_html": html}

    monkeypatch.setattr(sd, "fetch_json", fake_fetch_json)
    monkeypatch.setattr(sd, "_evaluate", lambda client, item, min_tier, min_reviews: sd.build_deal(
        item, "Mostly Positive", 24653, 70.6
    ))

    deals = sd.fetch_deals(min_discount=30, max_pages=5)
    assert 1097840 in {d.appid for d in deals}
    # Bounded: stopped once a short (< page size) page signaled the end, not 5 full pages.
    assert len(calls) == 3


def test_fetch_deals_respects_max_pages_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    """The scan must not run away indefinitely even if Steam has endless pages."""
    full_page = sd.parse_search_page(
        _search_page(*[(i, f"Filler {i}", 40, "19.99", "11.99") for i in range(100)])
    )
    calls: list[str] = []

    def fake_fetch_json(url: str, *, client: httpx.Client | None = None, headers: Any = None) -> dict[str, Any]:
        calls.append(url)
        html = _search_page(
            *[(r["id"], r["name"], r["discount_percent"], "0.00", "0.00") for r in full_page]
        )
        return {"results_html": html}

    monkeypatch.setattr(sd, "fetch_json", fake_fetch_json)
    monkeypatch.setattr(sd, "_evaluate", lambda client, item, min_tier, min_reviews: None)

    sd.fetch_deals(min_discount=30, max_pages=3)
    assert len(calls) == 3  # never exceeds the configured bound


def test_fetch_deals_propagates_source_error_instead_of_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """A broken/rate-limited search page must surface as a failure, not a quiet []."""

    def failing_fetch_json(url: str, *, client: httpx.Client | None = None, headers: Any = None) -> Any:
        raise SourceError("boom")

    monkeypatch.setattr(sd, "fetch_json", failing_fetch_json)

    with pytest.raises(SourceError):
        sd.fetch_deals(min_discount=30, max_pages=2)
