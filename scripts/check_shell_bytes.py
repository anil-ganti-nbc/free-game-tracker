"""Reject carriage returns in production shell scripts and release archives."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import tarfile
from pathlib import Path


def shell_paths(names: list[str]) -> list[str]:
    return sorted(
        name
        for name in names
        if (name.startswith("scripts/") or name.startswith("deploy/"))
        and name.endswith(".sh")
        and name.count("/") == 1
    )


def check_bytes(name: str, data: bytes, revision: str | None) -> None:
    if b"\r" in data:
        raise ValueError(f"{name}: CR bytes in production shell script")
    if revision:
        canonical = subprocess.check_output(
            ["git", "cat-file", "blob", f"{revision}:{name}"],
            cwd=Path(__file__).resolve().parents[1],
        )
        if data != canonical:
            raise ValueError(f"{name}: bytes differ from Git blob at {revision}")
    print(f"{name}: LF={data.count(bytes([10]))} SHA256={hashlib.sha256(data).hexdigest()}")


def check_root(root: Path, revision: str | None) -> None:
    names = shell_paths(
        [
            p.relative_to(root).as_posix()
            for base in ("scripts", "deploy")
            for p in (root / base).glob("*.sh")
        ]
    )
    if "scripts/entrypoint.sh" not in names:
        raise ValueError("scripts/entrypoint.sh missing")
    for name in names:
        check_bytes(name, (root / name).read_bytes(), revision)


def check_archive(archive: Path, revision: str | None) -> None:
    with tarfile.open(archive, "r:gz") as stream:
        names = shell_paths(stream.getnames())
        if "scripts/entrypoint.sh" not in names:
            raise ValueError("scripts/entrypoint.sh missing from archive")
        for name in names:
            member = stream.extractfile(name)
            if member is None:
                raise ValueError(f"{name}: not a regular archive file")
            check_bytes(name, member.read(), revision)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--revision", help="Compare shell bytes to this commit's Git blobs")
    args = parser.parse_args()
    try:
        if args.archive:
            check_archive(args.archive, args.revision)
        else:
            check_root(args.root, args.revision)
    except (OSError, ValueError, subprocess.CalledProcessError, tarfile.TarError) as exc:
        print(f"shell byte check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
