"""Executable shell bytes are a build input, including on Windows."""

from __future__ import annotations

import io
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
from _pytest.capture import CaptureFixture
from _pytest.monkeypatch import MonkeyPatch

from scripts import check_shell_bytes

ROOT = Path(__file__).resolve().parents[2]


def run_check(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str], *args: str
) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "argv", ["check_shell_bytes.py", *args])
    code = check_shell_bytes.main()
    output = capsys.readouterr()
    return code, output.out, output.err


def test_production_shell_source_has_no_carriage_returns(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    code, output, error = run_check(monkeypatch, capsys, "--root", str(ROOT))
    assert code == 0, error
    assert "scripts/entrypoint.sh" in output
    assert "scripts/make_snapshot.sh" in output
    assert "deploy/run.sh" in output


@pytest.mark.parametrize("bad_bytes", [b"set -eu\r\n", b"set -eu\r"])
def test_source_byte_gate_rejects_carriage_returns(
    tmp_path: Path, bad_bytes: bytes, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "entrypoint.sh").write_bytes(b"#!/bin/sh\n" + bad_bytes)
    code, _, error = run_check(monkeypatch, capsys, "--root", str(tmp_path))
    assert code == 1
    assert "CR bytes" in error


def test_archive_byte_gate_rejects_corrupted_entrypoint(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    archive = tmp_path / "source.tar.gz"
    data = b"#!/bin/sh\r\nset -eu\r\n"
    with tarfile.open(archive, "w:gz") as stream:
        member = tarfile.TarInfo("scripts/entrypoint.sh")
        member.size = len(data)
        stream.addfile(member, io.BytesIO(data))
    code, _, error = run_check(monkeypatch, capsys, "--archive", str(archive))
    assert code == 1
    assert "CR bytes" in error


@pytest.mark.skipif(sys.platform == "win32", reason="/bin/sh is unavailable on Windows")
def test_dash_rejects_crlf_set_option(tmp_path: Path) -> None:
    script = tmp_path / "entrypoint.sh"
    script.write_bytes(b"#!/bin/sh\r\nset -eu\r\n")
    result = subprocess.run(["/bin/sh", str(script)], capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "set:" in result.stderr


def test_git_archive_preserves_canonical_shell_bytes(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    archive = tmp_path / "source.tar.gz"
    subprocess.run(
        [
            "git",
            "-c",
            "core.autocrlf=true",
            "archive",
            "--format=tar.gz",
            "-o",
            str(archive),
            "HEAD",
        ],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    code, _, error = run_check(monkeypatch, capsys, "--archive", str(archive))
    assert code == 0, error
    with tarfile.open(archive, "r:gz") as stream:
        for name in ("scripts/entrypoint.sh", "scripts/make_snapshot.sh", "deploy/run.sh"):
            member = stream.extractfile(name)
            assert member is not None
            assert member.read() == (ROOT / name).read_bytes()
