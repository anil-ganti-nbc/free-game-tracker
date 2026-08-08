"""Double-click launcher: starts the Newsroom dashboard (if not already
running) and opens it in your default browser.

Source for "Launch Dashboard.exe" (see README for how to rebuild it with
PyInstaller). Meant to be run from the project root, or as the packaged exe
sitting next to it.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8765
URL = f"http://{HOST}:{PORT}"
STARTUP_TIMEOUT_SECONDS = 20


def _is_listening() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((HOST, PORT)) == 0


def _project_root() -> Path:
    # When frozen by PyInstaller, the exe is expected to sit in the project
    # root (next to .venv); otherwise this file already lives there.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _start_server(root: Path) -> bool:
    newsroom_exe = root / ".venv" / "Scripts" / "newsroom.exe"
    python_exe = root / ".venv" / "Scripts" / "python.exe"
    if not newsroom_exe.exists() or not python_exe.exists():
        print(f"Could not find the Newsroom install under {root}\\.venv\\Scripts.")
        print("Run 'uv sync' in that folder first, then try again.")
        return False

    log_dir = root / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = open(log_dir / "dashboard.log", "a", encoding="utf-8")

    creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    subprocess.Popen(
        [str(python_exe), str(newsroom_exe), "serve"],
        cwd=str(root),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )

    for _ in range(int(STARTUP_TIMEOUT_SECONDS / 0.5)):
        if _is_listening():
            return True
        time.sleep(0.5)
    return False


def main() -> int:
    root = _project_root()
    if not _is_listening() and not _start_server(root):
        print(f"Dashboard did not start within {STARTUP_TIMEOUT_SECONDS}s. Check logs\\dashboard.log.")
        input("Press Enter to close...")
        return 1
    webbrowser.open(URL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
