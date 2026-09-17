import hashlib
import json
from pathlib import Path

import clank_reddit


def test_shared_transport_manifest() -> None:
    root = Path(__file__).resolve()
    while not (root / "pyproject.toml").exists():
        root = root.parent
    manifest = json.loads((root / "docs/REDDIT_TRANSPORT.json").read_text())
    assert (
        hashlib.sha256((root / manifest["vendored_path"]).read_bytes()).hexdigest()
        == manifest["sha256"]
    )
    assert manifest["version"] == clank_reddit.VERSION
