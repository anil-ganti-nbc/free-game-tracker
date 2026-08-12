"""Category -> Discord-notification coverage invariant.

Regression guard for the subscription-notification incident: Category.SUBSCRIPTION
was emitted by three sources for months with no Discord delivery path, and nothing
caught it because "categories a source can emit" and "categories notify.py
handles" were never checked against each other. See
SUBSCRIPTION_NOTIFICATION_INCIDENT_REPORT.md for the full history.

This test does NOT hand-maintain a list of "categories in use" — that is
exactly the kind of list that goes stale independently of the code it's meant
to describe. Instead it derives which categories are actually emittable by
scanning the source of every fetcher registered in newsroom.cli._SOURCES (the
same registry the real pipeline runs from), falling back to NewsEvent's own
model default for any source that never references Category explicitly. The
only hand-maintained side is newsroom.notify.CATEGORY_NOTIFIERS itself — a
human has to declare "yes, I built a delivery path for this" the same way
newsroom.cli._SOURCES declares "yes, this source is wired up" — but that
declaration can't itself go silently stale, because this test checks it
against the derived set every run.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable

from newsroom.cli import _SOURCES
from newsroom.models import Category, Confidence, NewsEvent, PromotionType, Source
from newsroom.notify import CATEGORY_NOTIFIERS

_CATEGORY_REF_RE = re.compile(r"\bCategory\.([A-Z_][A-Z0-9_]*)\b")


def _default_category() -> Category:
    """NewsEvent's own default — what a source gets if it never sets category=."""
    default = NewsEvent.model_fields["category"].default
    assert isinstance(default, Category)
    return default


def _categories_used_by(fetcher: Callable[[], list[NewsEvent]]) -> set[Category]:
    """Every Category value a registered source's module can construct.

    Scans the fetcher's own module source for explicit `Category.X`
    references. A module with none is relying on NewsEvent's default
    category (true today of epic/steam/gog/gamerpower).
    """
    module = inspect.getmodule(fetcher)
    assert module is not None, f"could not resolve a module for {fetcher!r}"
    source = inspect.getsource(module)
    found = {Category(name.lower()) for name in _CATEGORY_REF_RE.findall(source)}
    return found or {_default_category()}


def _all_used_categories() -> set[Category]:
    used: set[Category] = set()
    for fetcher in _SOURCES.values():
        used |= _categories_used_by(fetcher)
    return used


def test_every_registered_source_category_has_a_discord_path() -> None:
    """If a registered source can emit a category, notify.py must handle it.

    This is exactly the check that would have failed the moment
    Category.SUBSCRIPTION was added to playstation_plus/xbox_game_pass/
    geforce_now without a matching CATEGORY_NOTIFIERS entry.
    """
    used = _all_used_categories()
    handled = set(CATEGORY_NOTIFIERS)
    missing = used - handled
    assert not missing, (
        f"Registered source(s) can emit {missing}, which has no Discord "
        f"delivery path in newsroom.notify.CATEGORY_NOTIFIERS. Add a payload "
        f"builder + notify_* function for it, or explicitly document why "
        f"that category is intentionally excluded from Discord."
    )


def test_used_category_derivation_is_not_trivially_empty() -> None:
    """Guards the derivation mechanism itself: if _SOURCES were ever emptied,
    or every fetcher's module failed to resolve, the coverage test above
    would vacuously pass. Fail loudly instead."""
    assert _SOURCES, "newsroom.cli._SOURCES is empty — nothing to check coverage against"
    assert _all_used_categories()


def test_category_notifiers_registry_is_not_trivially_empty() -> None:
    """Same guard on the other side: an accidentally-emptied CATEGORY_NOTIFIERS
    would make the coverage test vacuously fail-safe rather than actually
    checking anything meaningful."""
    assert CATEGORY_NOTIFIERS


def test_category_notifiers_are_behaviourally_functional() -> None:
    """Declarative registration isn't enough on its own — a stale entry that
    points at a builder which no longer actually handles that category would
    still "pass" a purely declarative coverage check. Prove each registered
    builder produces a real payload for a synthetic event of the category it
    claims to handle."""
    for category, builder in CATEGORY_NOTIFIERS.items():
        event = NewsEvent(
            source=Source.EPIC,
            category=category,
            title="Coverage Probe",
            url="https://example.invalid/coverage-probe",
            promotion_type=PromotionType.GIVEAWAY,
            confidence=Confidence(score=100, reasons=["synthetic coverage probe"]),
        )
        payload = builder([event])
        assert payload is not None, (
            f"CATEGORY_NOTIFIERS[{category!r}] = {builder!r} did not build a "
            f"payload for a synthetic {category!r} event — this registration "
            f"is stale relative to the builder's actual filtering logic."
        )


def test_known_categories_are_exactly_two_and_both_covered() -> None:
    """Documents the current, complete state explicitly: at the time of this
    hardening pass, Category has exactly two members and both have a Discord
    path. No category is currently intentionally excluded from delivery. If
    this test starts failing because a new Category member was added, that's
    the intended signal — go decide (and document) whether it needs a
    delivery path or is deliberately Discord-silent, then update this test
    and CATEGORY_NOTIFIERS together.
    """
    assert set(Category) == {Category.GAME_PROMOTION, Category.SUBSCRIPTION}
    assert set(CATEGORY_NOTIFIERS) == set(Category)
