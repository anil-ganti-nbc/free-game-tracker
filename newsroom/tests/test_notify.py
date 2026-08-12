"""Tests for Discord notification building and posting (no real network)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from newsroom.compare import RunDiff
from newsroom.models import (
    AccessModel,
    Category,
    Confidence,
    EventType,
    NewRelease,
    NewsEvent,
    OwnershipModel,
    PromotionType,
    Source,
    SteamDeal,
)
from newsroom.notify import (
    build_breakout_payload,
    build_deal_payload,
    build_discord_payload,
    build_subscription_payload,
    notify_new_giveaways,
    notify_new_subscription_events,
    post_discord,
)

WEBHOOK = "https://discord.com/api/webhooks/1/abc"


def _event(title: str = "Sample Free Game", score: int = 100) -> NewsEvent:
    return NewsEvent(
        source=Source.EPIC,
        title=title,
        url="https://store.epicgames.com/en-US/p/x",
        promotion_type=PromotionType.GIVEAWAY,
        original_price=19.99,
        current_price=0.0,
        promotion_end=datetime(2026, 7, 25, tzinfo=UTC),
        confidence=Confidence(score=score, reasons=["MSRP changed from paid to free"]),
    )


def test_payload_has_one_embed_per_game() -> None:
    payload = build_discord_payload([_event()])
    assert payload is not None
    assert len(payload["embeds"]) == 1
    embed = payload["embeds"][0]
    assert embed["title"] == "Sample Free Game"
    assert embed["url"] == "https://store.epicgames.com/en-US/p/x"
    field_values = {f["name"]: f["value"] for f in embed["fields"]}
    assert field_values["Store"] == "epic"
    assert field_values["Price"] == "$19.99 → Free"
    assert field_values["Confidence"] == "100"


def test_no_payload_when_empty() -> None:
    assert build_discord_payload([]) is None


def test_min_confidence_filters_out_low_scores() -> None:
    events = [_event("High", 100), _event("Low", 40)]
    payload = build_discord_payload(events, min_confidence=70)
    assert payload is not None
    titles = {e["title"] for e in payload["embeds"]}
    assert titles == {"High"}


def test_more_than_ten_games_are_capped() -> None:
    events = [_event(f"Game {i}") for i in range(13)]
    payload = build_discord_payload(events)
    assert payload is not None
    assert len(payload["embeds"]) == 10
    assert "Showing first 10" in payload["content"]


def test_subscription_events_suppressed() -> None:
    from newsroom.models import Category

    sub_event = _event("Sub Game", 100)
    sub_event.category = Category.SUBSCRIPTION
    assert build_discord_payload([sub_event]) is None


def test_notify_skips_when_no_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no webhook, nothing is posted and no client is touched."""
    monkeypatch.setattr("newsroom.notify.settings.discord_webhook_url", None)
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(204)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = notify_new_giveaways(RunDiff(new=[_event()]), webhook_url=None, client=client)
    assert result is False
    assert calls == []


def test_notify_posts_new_giveaways() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(204)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = notify_new_giveaways(RunDiff(new=[_event()]), webhook_url=WEBHOOK, client=client)
    assert result is True
    assert len(seen) == 1
    assert seen[0]["embeds"][0]["title"] == "Sample Free Game"


def test_breakout_payload_fields() -> None:
    release = NewRelease(
        appid=42,
        name="Breakout Hit",
        url="https://store.steampowered.com/app/42",
        release_date=datetime(2026, 7, 15, tzinfo=UTC),
        review_desc="Overwhelmingly Positive",
        total_reviews=2000,
        positive_pct=95.0,
    )
    payload = build_breakout_payload([release])
    assert payload is not None
    embed = payload["embeds"][0]
    assert embed["title"] == "Breakout Hit"
    fields = {f["name"]: f["value"] for f in embed["fields"]}
    assert fields["Reviews"] == "Overwhelmingly Positive"
    assert fields["Positive"] == "95%"


def test_breakout_payload_none_when_empty() -> None:
    assert build_breakout_payload([]) is None


def test_deal_payload_fields() -> None:
    deal = SteamDeal(
        appid=5,
        name="Great Deal",
        url="https://store.steampowered.com/app/5",
        discount_percent=40,
        original_price=39.99,
        final_price=23.99,
        review_desc="Very Positive",
        total_reviews=5000,
        positive_pct=96.0,
        discount_end=datetime(2026, 7, 25, tzinfo=UTC),
    )
    payload = build_deal_payload([deal])
    assert payload is not None
    embed = payload["embeds"][0]
    assert embed["title"] == "Great Deal"
    fields = {f["name"]: f["value"] for f in embed["fields"]}
    assert fields["Discount"] == "-40%"
    assert fields["Price"] == "$39.99 → $23.99"
    assert fields["Reviews"] == "Very Positive"


def test_deal_payload_none_when_empty() -> None:
    assert build_deal_payload([]) is None


def test_post_is_fault_isolated_on_error() -> None:
    """A failing webhook must return False, not raise."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert post_discord(WEBHOOK, {"content": "x"}, client=client) is False


def test_post_retries_after_rate_limit() -> None:
    """A 429 is retried (honouring Retry-After) and then succeeds."""
    statuses = [429, 204]

    def handler(request: httpx.Request) -> httpx.Response:
        code = statuses.pop(0)
        if code == 429:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(code)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert post_discord(WEBHOOK, {"content": "x"}, client=client) is True
    assert statuses == []  # both responses consumed


def test_post_gives_up_after_persistent_rate_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert post_discord(WEBHOOK, {"content": "x"}, client=client) is False


# --- Subscription-access events (PS Plus / Xbox Game Pass / GeForce Now) ---
#
# Regression coverage for the Helldivers 2 incident: build_discord_payload
# (the giveaway-shaped embed) correctly excludes Category.SUBSCRIPTION events
# (see test_subscription_events_suppressed above) — but historically nothing
# else picked them up, so they were never announced at all. These prove the
# sibling path exists, is correctly labeled (never "free"/ownership language),
# and is wired to fire only for subscription-category events.


def _sub_event(
    title: str = "Some Game",
    score: int = 95,
    service: str = "playstation_plus",
    tiers: list[str] | None = None,
    event_type: EventType = EventType.CATALOG_ADDITION,
) -> NewsEvent:
    return NewsEvent(
        source=Source.PLAYSTATION_PLUS,
        category=Category.SUBSCRIPTION,
        title=title,
        url="https://blog.playstation.com/2026/08/12/some-article/",
        promotion_type=PromotionType.GIVEAWAY,
        event_type=event_type,
        access_model=AccessModel.SUBSCRIPTION_CATALOG,
        ownership_model=OwnershipModel.ACCESSIBLE_WHILE_IN_CATALOG,
        service=service,
        tiers=tiers or ["extra", "premium"],
        available_from=datetime(2026, 8, 12, tzinfo=UTC),
        confidence=Confidence(score=score, reasons=["Official PlayStation Blog format detected"]),
    )


def test_subscription_payload_never_says_free_or_price() -> None:
    payload = build_subscription_payload([_sub_event("Big Paid Game")])
    assert payload is not None
    embed = payload["embeds"][0]
    field_values = {f["name"]: f["value"] for f in embed["fields"]}
    rendered = " ".join(field_values.values()) + payload["content"]
    assert "free" not in rendered.lower()
    assert "Price" not in field_values
    assert field_values["Service"] == "Playstation Plus"
    assert field_values["Tier"] == "Extra / Premium"
    assert field_values["Availability"] == "2026-08-12"
    assert field_values["Access type"] == "Subscription access (not ownership)"


def test_subscription_payload_ignores_game_promotion_events() -> None:
    """The inverse of build_discord_payload's own category filter."""
    assert build_subscription_payload([_event("Normal Giveaway")]) is None


def test_subscription_payload_empty_when_no_events() -> None:
    assert build_subscription_payload([]) is None


def test_notify_subscription_events_skips_when_no_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("newsroom.notify.settings.discord_webhook_url", None)
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(204)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = notify_new_subscription_events(
        RunDiff(new=[_sub_event()]), webhook_url=None, client=client
    )
    assert result is False
    assert calls == []


def test_notify_posts_new_subscription_events() -> None:
    """End-to-end: a Helldivers-2-shaped RunDiff reaches a Discord POST."""
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(204)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    diff = RunDiff(new=[_sub_event("Major Paid Game")])
    result = notify_new_subscription_events(diff, webhook_url=WEBHOOK, client=client)
    assert result is True
    assert len(seen) == 1
    assert seen[0]["embeds"][0]["title"] == "Major Paid Game"


def test_notify_subscription_events_does_not_duplicate_giveaways() -> None:
    """A RunDiff mixing a giveaway and a subscription event posts each once,
    through its own function, never both from the same one."""
    diff = RunDiff(new=[_event("Epic Giveaway"), _sub_event("PS Plus Game")])

    giveaway_payload = build_discord_payload(diff.new)
    subscription_payload = build_subscription_payload(diff.new)

    assert giveaway_payload is not None
    assert [e["title"] for e in giveaway_payload["embeds"]] == ["Epic Giveaway"]
    assert subscription_payload is not None
    assert [e["title"] for e in subscription_payload["embeds"]] == ["PS Plus Game"]
