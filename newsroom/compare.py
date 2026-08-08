"""Detect what changed between the previous run and the current one.

This is the heart of the "discover before humans do" job: given the set of free
games we saw last time and the set we see now, work out what is newly free, what
is about to end, and what has disappeared. It is a pure function over two lists
of :class:`~newsroom.models.NewsEvent` — it touches no database and does no I/O,
which makes it trivial to test.

Events are matched across runs by :attr:`NewsEvent.event_key` (``source:url``).
The three buckets are deliberately disjoint:

* **new** — present now, not present last run. These are the story candidates.
* **ending_soon** — present in *both* runs and ending within the threshold. A
  brand-new giveaway that also ends soon is reported as *new*, not here, so no
  event appears twice.
* **expired** — present last run, absent now. The giveaway has gone.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from newsroom.models import NewsEvent

#: Default window, in hours, for treating a promotion as "ending soon".
DEFAULT_ENDING_SOON_HOURS = 48


def deduplicate(events: list[NewsEvent]) -> list[NewsEvent]:
    """Drop duplicate offers within a single run, keeping the first seen.

    A run should hold at most one event per ``event_key``. Sources occasionally
    surface the same offer twice (for example, several editions that resolve to
    one store page), and storage enforces a unique key — so we collapse them
    here before comparing or persisting.
    """
    seen: set[str] = set()
    unique: list[NewsEvent] = []
    for event in events:
        if event.event_key in seen:
            continue
        seen.add(event.event_key)
        unique.append(event)
    return unique


@dataclass(frozen=True)
class RunDiff:
    """The outcome of comparing two runs. Three disjoint lists of events."""

    new: list[NewsEvent] = field(default_factory=list)
    ending_soon: list[NewsEvent] = field(default_factory=list)
    expired: list[NewsEvent] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        """True if this run surfaced anything worth a report."""
        return bool(self.new or self.ending_soon or self.expired)


def compare(
    previous: list[NewsEvent],
    current: list[NewsEvent],
    ending_soon_hours: int = DEFAULT_ENDING_SOON_HOURS,
) -> RunDiff:
    """Compare last run's events against this run's and bucket the differences.

    Args:
        previous: Events stored from the prior run.
        current: Events detected in this run.
        ending_soon_hours: How soon a continuing promotion must end to count as
            "ending soon".

    Returns:
        A :class:`RunDiff` with disjoint ``new``, ``ending_soon``, and
        ``expired`` lists.
    """
    previous_keys = {event.event_key for event in previous}
    current_keys = {event.event_key for event in current}

    new = [e for e in current if e.event_key not in previous_keys]
    expired = [e for e in previous if e.event_key not in current_keys]
    continuing = [e for e in current if e.event_key in previous_keys]
    ending_soon = [e for e in continuing if e.is_ending_soon(ending_soon_hours)]

    return RunDiff(new=new, ending_soon=ending_soon, expired=expired)
