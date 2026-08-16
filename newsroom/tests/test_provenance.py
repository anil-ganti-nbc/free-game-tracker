"""Tests for Git-revision provenance exposure (runtime_bridge / settings)."""

from __future__ import annotations

import pytest

from newsroom import runtime_bridge
from newsroom.config import settings


def test_source_revision_defaults_to_unknown() -> None:
    # A local/unconfigured build must never fabricate an identity.
    assert settings.source_revision == "unknown"


def test_version_info_exposes_source_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "source_revision", "abc123def456")
    info = runtime_bridge.get_version_info()
    assert info["source_revision"] == "abc123def456"


def test_identity_exposes_source_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "source_revision", "abc123def456")
    identity = runtime_bridge.get_identity()
    payload = runtime_bridge.as_jsonable(identity)
    assert payload["source_revision"] == "abc123def456"


def test_identity_reports_unknown_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "source_revision", "unknown")
    identity = runtime_bridge.get_identity()
    payload = runtime_bridge.as_jsonable(identity)
    assert payload["source_revision"] == "unknown"
