"""Cross-process single-instance lock for the ``newsroom run`` CLI command.

Prevents two independent invocations (e.g. an hourly cron tick firing while
the previous hour's run is still going) from writing the same SQLite
database concurrently.

Uses an OS-level advisory file lock (``fcntl.flock`` on POSIX and
``msvcrt.locking`` on Windows) rather than a PID-file
existence/liveness check. This matters specifically because every
``docker compose run --rm`` invocation gets its own PID namespace, so the
main process is *always* PID 1 from its own point of view — a stale-lock
check that asks "is the PID recorded in the old lock file still alive"
would always answer yes when asked by a fresh container, since that
container's own init process trivially satisfies the query regardless of
whether the *actual* old run is still going. An OS lock sidesteps this
entirely: the kernel ties the lock to the file's inode, which is genuinely
shared across containers via the bind-mounted/volume-backed lock file (the
same mechanism that already makes SQLite's own locking work correctly
across separate containers here), and the kernel automatically releases the
lock when the holding process's file descriptor closes — for any reason,
including a crash or an OOM-kill — without needing any liveness check at
all.

Non-blocking by design: a refusal means "skip this invocation," not "wait."
"""

from __future__ import annotations

import json
import logging
import os
import socket
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl

log = logging.getLogger("newsroom.run_lock")


class RunLockError(Exception):
    """Raised when the run lock is already held by another process."""


@dataclass
class RunLock:
    path: Path
    pid: int
    acquired_at: float


def _lock(fd: int) -> None:
    if os.name == "nt":
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"\0")
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(fd: int) -> None:
    if os.name == "nt":
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)


def _read_holder(path: Path) -> dict[str, object] | None:
    """Best-effort read of who (probably) holds the lock, for a useful message
    only — never consulted to decide whether the lock can be acquired."""
    try:
        result: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
        return result
    except Exception:
        return None


@contextmanager
def acquire(path: str | Path) -> Iterator[RunLock]:
    """Acquire the cross-process run lock, or raise ``RunLockError`` immediately.

    Usage::

        with run_lock.acquire(lock_path) as lock:
            ...  # do the real work

    The lock is released automatically on the way out of the ``with`` block,
    whether it exits normally or via an exception.
    """
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        _lock(fd)
    except OSError as exc:
        holder = _read_holder(lock_path)
        os.close(fd)
        if holder:
            detail = f" (pid={holder.get('pid')}, started={holder.get('started_at_iso')})"
        else:
            detail = ""
        raise RunLockError(
            f"another newsroom run is already active{detail} — lock={lock_path}. "
            f"Skipping this invocation."
        ) from exc

    pid = os.getpid()
    started_at = time.time()
    payload: dict[str, object] = {
        "pid": pid,
        "hostname": socket.gethostname(),
        "started_at": started_at,
        "started_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    os.ftruncate(fd, 0)
    os.write(fd, json.dumps(payload, indent=2).encode("utf-8"))
    os.fsync(fd)
    log.info("acquired run lock %s (pid=%s)", lock_path, pid)

    lock = RunLock(path=lock_path, pid=pid, acquired_at=started_at)
    try:
        yield lock
    finally:
        try:
            _unlock(fd)
        finally:
            os.close(fd)
        log.info("released run lock %s", lock_path)
