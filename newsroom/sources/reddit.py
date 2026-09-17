"""Free Game Tracker's discovery and INTEL classifications; no promotion terms invented."""

from __future__ import annotations

import re
from collections.abc import Callable

import httpx

from clank_reddit import Submission, retrieve

GetPage = Callable[[str], tuple[int, str]]

FGF_SOURCES = {"reddit_free_game_findings": "FreeGameFindings"}
INTEL_SOURCES = {"reddit_gaming_leaks": "GamingLeaksAndRumours"}
SOURCES = {**FGF_SOURCES, **INTEL_SOURCES}


def classify(post: Submission) -> str:
    title = post.title.lower()
    if post.subreddit == "FreeGameFindings":
        if re.search(r"\[game\]", title):
            return "giveaway_claim_unverified"
        return "non_game_or_unclassified"
    if post.subreddit != "GamingLeaksAndRumours":
        return "out_of_scope"
    # Questions, requests, meta and giveaways are not game leaks. Preserve them
    # as observations without surfacing them as rumour candidates.
    if "?" in title or re.search(
        r"\b(meta|weekly discussion|free game|giveaway|wishlist)\b", title
    ):
        return "non_leak_or_unclassified"
    if re.search(
        r"\b(gpu|cpu|graphics card|processor|console|ps6|handheld)\b", title
    ) and not re.search(r"\b(game|gameplay|dlc|sequel|remake|expansion)\b", title):
        return "non_leak_or_unclassified"
    if re.search(
        r"\b(leak(?:ed|s)?|rumou?r|datamin(?:e|ed)|reportedly|allegedly)\b", title
    ):
        return "game_rumour_unverified"
    return "non_leak_or_unclassified"


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
