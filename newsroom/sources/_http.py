"""Shared HTTP plumbing for sources.

Extracted once a second and third source needed the same fetch-with-retries
behaviour that originally lived in ``epic.py``. Keeping it here means every
sensor gets identical, well-behaved networking — timeouts, bounded retries, and
a single failure type — without repeating the loop.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from newsroom.config import settings

logger = logging.getLogger(__name__)

#: A neutral identifier so stores can attribute traffic if they wish.
DEFAULT_HEADERS = {"User-Agent": "newsroom/0.1 (+internal)"}


class SourceError(Exception):
    """Raised when a source cannot be fetched. The run continues without it."""


def fetch_json(
    url: str,
    *,
    client: httpx.Client | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    """GET ``url`` and return decoded JSON, retrying transient failures.

    Args:
        url: The endpoint to fetch.
        client: An optional httpx client (for testing or connection reuse). One
            is created and closed automatically when not supplied.
        headers: Optional headers; a default User-Agent is used otherwise.

    Returns:
        The decoded JSON (typically a dict).

    Raises:
        SourceError: If the endpoint cannot be fetched after all retries.
    """
    owns_client = client is None
    client = client or httpx.Client(headers=headers or DEFAULT_HEADERS)
    try:
        return _get_json_with_retries(client, url)
    finally:
        if owns_client:
            client.close()


def _get_json_with_retries(client: httpx.Client, url: str) -> Any:
    """GET a URL and return decoded JSON, retrying up to the configured limit."""
    last_error: Exception | None = None
    for attempt in range(settings.http_max_retries + 1):
        try:
            response = client.get(url, timeout=settings.http_timeout_seconds)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as error:
            last_error = error
            logger.warning(
                "Fetch attempt %d/%d for %s failed: %s",
                attempt + 1,
                settings.http_max_retries + 1,
                url,
                error,
            )
            if attempt < settings.http_max_retries:
                time.sleep(settings.http_retry_backoff_seconds * (attempt + 1))
    raise SourceError(
        f"Fetch failed after {settings.http_max_retries + 1} attempts: {url}"
    ) from last_error
