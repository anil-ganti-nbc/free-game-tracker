"""Domain discovery admission using newsroom transactions and run locking.

Caller holds newsroom.lock, as for every pipeline collection. No notification
path exists for unverified discovery; no promotion or auto-admission is provided.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from newsroom import database as db
from newsroom.sources import reddit


def collect(
    source: str,
    *,
    get: reddit.GetPage | None = None,
    persist: bool = True,
    code_revision: str = "UNKNOWN",
) -> dict[str, Any]:
    if source not in reddit.SOURCES:
        raise ValueError("Unknown discovery source")
    now = datetime.now(UTC)
    if not persist:
        posts = reddit.fetch(source, get)
        return {"observed": len(posts), "delivery": "blocked", "persisted": False}
    with db.session_scope() as session:
        prior = session.scalar(
            select(db.DiscoveryRunRow.id)
            .where(db.DiscoveryRunRow.source == source, db.DiscoveryRunRow.status == "ok")
            .limit(1)
        )
        baseline = prior is None
        run = db.DiscoveryRunRow(
            source=source,
            started_at=now,
            baseline=baseline,
            evidence={"code_revision": code_revision, "delivery": "blocked"},
        )
        session.add(run)
        session.flush()
        run_id = run.id
    try:
        posts = reddit.fetch(source, get)
        new = 0
        with db.session_scope() as session:
            for post in posts:
                key = source + ":" + post.external_id
                row = session.get(db.DiscoveryObservationRow, key)
                policy = (
                    "fgt-reddit-intel-v1"
                    if source in reddit.INTEL_SOURCES
                    else "fgt-reddit-discovery-v2"
                )
                evidence = post.evidence() | {
                    "run_id": run_id,
                    "source_id": source,
                    "code_revision": code_revision,
                    "collected_at": now.isoformat(),
                    "classification_policy": policy,
                }
                if row is None:
                    row = db.DiscoveryObservationRow(
                        key=key,
                        source=source,
                        external_id=post.external_id,
                        title=post.title,
                        url=post.permalink,
                        classification=reddit.classify(post),
                        baseline=baseline,
                        first_seen=now,
                        last_seen=now,
                        evidence=[evidence],
                    )
                    session.add(row)
                    new += 1
                else:
                    row.last_seen = now
                    if row.evidence[-1]["raw_sha256"] != evidence["raw_sha256"]:
                        row.evidence = [*row.evidence, evidence]
                        row.title = post.title
                        row.classification = reddit.classify(post)
            saved_run = session.get(db.DiscoveryRunRow, run_id)
            assert saved_run is not None
            saved_run.status = "ok"
            saved_run.finished_at = datetime.now(UTC)
            saved_run.evidence = {
                "observed": len(posts),
                "new_observations": new,
                "collection_health": "ok",
                "persistence_health": "ok",
                "delivery": "blocked",
                "code_revision": code_revision,
            }
        db.record_source_result(source, ok=True, count=len(posts))
        return {
            "observed": len(posts),
            "new_observations": new,
            "baseline": baseline,
            "delivery": "blocked",
        }
    except Exception as exc:
        with db.session_scope() as session:
            saved_run = session.get(db.DiscoveryRunRow, run_id)
            assert saved_run is not None
            saved_run.status = "failed"
            saved_run.finished_at = datetime.now(UTC)
            saved_run.evidence = {
                "error": str(exc),
                "delivery": "blocked",
                "code_revision": code_revision,
            }
        db.record_source_result(source, ok=False, error=str(exc))
        raise
