"""Application entry point.

``newsroom.main:app`` is the console script declared in ``pyproject.toml`` and
is also runnable with ``python -m newsroom.main``.
"""

from __future__ import annotations

from newsroom.cli import app

if __name__ == "__main__":
    app()
