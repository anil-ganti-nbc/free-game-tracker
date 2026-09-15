"""Free Game Tracker's discovery classifications; no promotion terms invented."""

from __future__ import annotations

import re
from collections.abc import Callable

import httpx

from clank_reddit import Submission, retrieve

GetPage = Callable[[str], tuple[int, str]]

SOURCES = {"reddit_free_game_findings": "FreeGameFindings"}


def classify(post: Submission) -> str:
    title = post.title.lower()
    if post.subreddit != "FreeGameFindings":
        return "out_of_scope"
    if re.search(r"\[game\]", title):
        return "giveaway_claim_unverified"
    return "non_game_or_unclassified"


def fetch(source: str, get: GetPage | None = None) -> list[Submission]:
    community = SOURCES[source]
    if get is not None:
        return retrieve(community, get)
    with httpx.Client(
        timeout=20, follow_redirects=False, headers={"User-Agent": "Clank-domain-discovery/1.0"}
    ) as client:

        def get_page(url: str) -> tuple[int, str]:
            response = client.get(url)
            return response.status_code, response.text

        return retrieve(community, get_page)
