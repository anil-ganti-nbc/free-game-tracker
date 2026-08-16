"""Tests for the cross-process run lock (newsroom.run_lock).

Normal acquisition/refusal/release are tested directly against the module.
The "stale lock" scenario is tested by actually killing a subprocess that
holds the lock — the meaningful case for this design, since it proves the
kernel releases the flock automatically on process death rather than relying
on any PID-liveness check (see the module docstring for why that check would
be unreliable across separate Docker containers).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from newsroom import cli, database, run_lock
from newsroom.config import settings


def test_normal_acquisition(tmp_path: Path) -> None:
    lock_path = tmp_path / "newsroom.lock"
    with run_lock.acquire(lock_path) as lock:
        assert lock.path == lock_path
        assert lock.pid == os.getpid()
        assert lock_path.exists()


def test_second_acquisition_refused_while_first_held(tmp_path: Path) -> None:
    lock_path = tmp_path / "newsroom.lock"
    with (
        run_lock.acquire(lock_path),
        pytest.raises(run_lock.RunLockError, match="another newsroom run is already active"),
        run_lock.acquire(lock_path),
    ):
        pytest.fail("second acquire should not have succeeded")


def test_refusal_message_names_the_holder(tmp_path: Path) -> None:
    lock_path = tmp_path / "newsroom.lock"
    with run_lock.acquire(lock_path) as first:
        try:
            with run_lock.acquire(lock_path):
                pytest.fail("second acquire should not have succeeded")
        except run_lock.RunLockError as exc:
            assert str(first.pid) in str(exc)


def test_release_after_successful_run(tmp_path: Path) -> None:
    lock_path = tmp_path / "newsroom.lock"
    with run_lock.acquire(lock_path):
        pass
    # Lock released cleanly — a fresh acquire must succeed immediately.
    with run_lock.acquire(lock_path) as lock:
        assert lock.pid == os.getpid()


def test_release_after_exception(tmp_path: Path) -> None:
    lock_path = tmp_path / "newsroom.lock"
    with pytest.raises(ValueError), run_lock.acquire(lock_path):
        raise ValueError("simulated collector failure")
    # Even though the run raised, the lock must not still be held.
    with run_lock.acquire(lock_path) as lock:
        assert lock.pid == os.getpid()


def test_lock_file_contains_no_secrets_and_is_plain_json(tmp_path: Path) -> None:
    lock_path = tmp_path / "newsroom.lock"
    with run_lock.acquire(lock_path):
        content = lock_path.read_text(encoding="utf-8")
        assert "pid" in content
        assert "started_at" in content


def test_stale_lock_from_a_killed_process_is_reclaimed(tmp_path: Path) -> None:
    """Simulate a genuinely crashed holder (SIGKILL, no cleanup) and confirm a
    fresh acquire succeeds right away — the kernel released the flock when
    the process died, no manual staleness/timeout logic required."""
    lock_path = tmp_path / "newsroom.lock"
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import fcntl, os, time, sys; "
                f"fd = os.open({str(lock_path)!r}, os.O_CREAT | os.O_RDWR, 0o644); "
                "fcntl.flock(fd, fcntl.LOCK_EX); "
                "sys.stdout.write('locked\\n'); sys.stdout.flush(); "
                "time.sleep(60)"
            ),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None
        line = holder.stdout.readline()
        assert line.strip() == "locked"

        # Confirm the lock is genuinely held while the process is alive.
        with pytest.raises(run_lock.RunLockError), run_lock.acquire(lock_path):
            pytest.fail("acquire should not succeed while holder is alive")

        holder.kill()  # SIGKILL — no chance to run any cleanup code
        holder.wait(timeout=5)

        # Give the kernel a moment to tear down the dead process's fds.
        deadline = time.time() + 5
        last_error: Exception | None = None
        while time.time() < deadline:
            try:
                with run_lock.acquire(lock_path) as lock:
                    assert lock.pid == os.getpid()
                    return
            except run_lock.RunLockError as exc:  # pragma: no cover - retried below
                last_error = exc
                time.sleep(0.1)
        raise AssertionError(f"lock was never reclaimed after holder was killed: {last_error}")
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=5)


def test_cli_run_skips_cleanly_when_lock_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `run` command must exit 0 and touch neither the database nor the
    network when another run already holds the lock — a refusal is not a
    collector failure and must not appear as one in source_health."""
    monkeypatch.setattr(settings, "database_path", tmp_path / "test.db")
    monkeypatch.setattr(settings, "reports_dir", tmp_path / "reports")
    monkeypatch.setattr(settings, "discord_webhook_url", None)
    database.reset_engine()
    database.init_db()

    lock_path = tmp_path / "newsroom.lock"
    runner = CliRunner()
    with run_lock.acquire(lock_path):
        result = runner.invoke(cli.app, ["run"])

    assert result.exit_code == 0
    assert "Skipped" in result.output
    database.reset_engine()
    database.init_db()
    assert database.load_source_health() == []
