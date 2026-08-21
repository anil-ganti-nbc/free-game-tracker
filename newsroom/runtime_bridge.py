"""Stage 0.5-compatible runtime bridge: version / identity / health.

Thin adapter only. Does not run collectors, does not invent historical data,
and does not claim a release channel the deployment hasn't been promoted to.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from typing import Any

from newsroom import __version__ as PACKAGE_VERSION
from newsroom.config import settings

CLANK_ID = "free-game-tracker"

OperationalState: Any
IngestionState: Any
ReleaseChannel: Any
HealthPayload: Any
RuntimeIdentity: Any

try:
    _runtime_enums = import_module("clank_runtime.contracts.enums")
    _runtime_health = import_module("clank_runtime.contracts.health")
    _runtime_identity = import_module("clank_runtime.contracts.identity")
    _runtime_version = import_module("clank_runtime.version")
    IngestionState = vars(_runtime_enums)["IngestionState"]
    OperationalState = vars(_runtime_enums)["OperationalState"]
    ReleaseChannel = vars(_runtime_enums)["ReleaseChannel"]
    HealthPayload = vars(_runtime_health)["HealthPayload"]
    RuntimeIdentity = vars(_runtime_identity)["RuntimeIdentity"]
    RUNTIME_VERSION = vars(_runtime_version)["__version__"]
    RUNTIME_CONTRACT_VERSION = vars(_runtime_version)["RUNTIME_CONTRACT_VERSION"]
    HEALTH_CONTRACT_VERSION = vars(_runtime_version)["HEALTH_CONTRACT_VERSION"]
    _HAS_RUNTIME = True
except ImportError:  # pragma: no cover - clank_runtime is an optional, separate package
    _HAS_RUNTIME = False
    RUNTIME_VERSION = "unavailable"
    RUNTIME_CONTRACT_VERSION = "0.1.0-stage0"
    HEALTH_CONTRACT_VERSION = "0.1.0-stage0"
    OperationalState = None
    IngestionState = None
    ReleaseChannel = None
    HealthPayload = None
    RuntimeIdentity = None


def get_version_info() -> dict[str, str]:
    return {
        "clank_id": CLANK_ID,
        "clank_version": PACKAGE_VERSION,
        "package_name": "newsroom",
        "runtime_version": RUNTIME_VERSION,
        "runtime_contract_version": RUNTIME_CONTRACT_VERSION,
        "health_contract_version": HEALTH_CONTRACT_VERSION,
        "release_channel": settings.release_channel,
        "source_revision": settings.source_revision,
        "runtime_bridge": "stage1.2",
    }


def get_identity() -> Any:
    """Identity always reflects settings.release_channel — never hard-coded.

    A container image is a candidate until an operator explicitly sets
    NEWSROOM_RELEASE_CHANNEL=production in its deployment config. Defaulting
    otherwise keeps an unconfigured or freshly built image from claiming a
    maturity it hasn't earned.

    source_revision is threaded through the fallback dict below (the only
    path actually exercised today — clank_runtime is not an installed
    dependency of this project). RuntimeIdentity's own field set is not
    modified here, since that would mean changing an external, uninstalled
    package's contract rather than this project's code.
    """
    if _HAS_RUNTIME:
        try:
            channel = ReleaseChannel(settings.release_channel)
        except ValueError:
            channel = ReleaseChannel.EXPERIMENTAL
        return RuntimeIdentity(
            runtime_version=RUNTIME_VERSION,
            clank_id=CLANK_ID,
            clank_version=PACKAGE_VERSION,
            release_channel=channel,
        )
    return {
        "contract_version": RUNTIME_CONTRACT_VERSION,
        "runtime_version": RUNTIME_VERSION,
        "clank_id": CLANK_ID,
        "clank_version": PACKAGE_VERSION,
        "release_channel": settings.release_channel,
        "source_revision": settings.source_revision,
    }


def _db_path() -> Path:
    return Path(settings.database_path)


def get_health() -> Any:
    """Build health from process + DB + recorded source_health rows.

    Semantics:
    - process_liveness: always true if this function runs
    - application_readiness: DB file exists or parent is writable for init
    - last_attempted / last_successful from source_health when present
    - zero qualifying offers is NOT a failure
    - upstream failures reflected via status_reasons and degraded state
    - operational_state is independent of release_channel
    """
    from newsroom.database import init_db, load_source_health

    db = _db_path()
    reasons: list[str] = []
    parent = db.parent
    db_writable = parent.exists() and os.access(parent, os.W_OK)
    if not db_writable:
        reasons.append(f"database parent not writable: {parent}")

    last_attempt: datetime | None = None
    last_success: datetime | None = None
    error_sources: list[str] = []
    ok_sources = 0

    if db.exists():
        try:
            init_db()
            health_rows = load_source_health()
            for h in health_rows:
                if last_attempt is None or h.last_attempt_at > last_attempt:
                    last_attempt = h.last_attempt_at
                if h.last_success_at and (
                    last_success is None or h.last_success_at > last_success
                ):
                    last_success = h.last_success_at
                if h.last_status == "ok":
                    ok_sources += 1
                else:
                    error_sources.append(h.source)
                    if h.last_error:
                        reasons.append(f"{h.source}: {h.last_error}")
                    else:
                        reasons.append(f"{h.source}: last_status={h.last_status}")
            if not health_rows:
                reasons.append("no source health rows recorded yet")
        except Exception as exc:  # noqa: BLE001 — health must not raise
            reasons.append(f"health query failed: {exc}")
            db_writable = False
    else:
        reasons.append(f"database file missing: {db}")

    if error_sources and ok_sources == 0:
        state = "failed"
    elif error_sources:
        state = "degraded"
    elif not db.exists():
        state = "degraded"
    else:
        state = "healthy"

    version_info = get_version_info()
    observed = datetime.now(timezone.utc)
    reports_writable = (
        settings.reports_dir.exists() and os.access(settings.reports_dir, os.W_OK)
    ) or (
        not settings.reports_dir.exists()
        and os.access(settings.reports_dir.parent, os.W_OK)
    )

    if _HAS_RUNTIME:
        op = {
            "healthy": OperationalState.HEALTHY,
            "degraded": OperationalState.DEGRADED,
            "failed": OperationalState.FAILED,
        }.get(state, OperationalState.UNKNOWN)
        return HealthPayload(
            operational_state=op,
            process_liveness=True,
            application_readiness=db.exists() or db_writable,
            last_attempted_run=last_attempt,
            last_successful_run=last_success,
            database_writable=db_writable,
            evidence_path_writable=reports_writable,
            ingestion_state=IngestionState.UNKNOWN,
            version_info=version_info,
            status_reasons=reasons,
            observed_at=observed,
        )

    return {
        "contract_version": HEALTH_CONTRACT_VERSION,
        "operational_state": state,
        "process_liveness": True,
        "application_readiness": db.exists() or db_writable,
        "last_attempted_run": last_attempt.isoformat() if last_attempt else None,
        "last_successful_run": last_success.isoformat() if last_success else None,
        "database_writable": db_writable,
        "evidence_path_writable": reports_writable,
        "ingestion_state": "unknown",
        "version_info": version_info,
        "status_reasons": reasons,
        "observed_at": observed.isoformat(),
    }


def as_jsonable(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return obj
