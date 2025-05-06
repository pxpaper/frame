#!/usr/bin/env python3
"""
Boot helper for PixelPaper

• Waits (up to 90 s) for real connectivity instead of a blind sleep
• Updates the repo only when online
• Always launches gui.py so BLE provisioning works even offline
"""
import subprocess
import time
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------
SCRIPT_DIR   = Path(__file__).resolve().parent
VENV_PYTHON  = SCRIPT_DIR / "venv" / "bin" / "python3"
GUI_SCRIPT   = SCRIPT_DIR / "gui.py"

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def wait_for_network(max_secs: int = 90) -> bool:
    """
    Block until NetworkManager reports full connectivity or until
    *max_secs* have elapsed. Returns True if online, False otherwise.
    """
    try:
        subprocess.run(
            ["nm-online", "--wait-for-startup", "--timeout", str(max_secs)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def update_repo() -> None:
    """
    Hard‑reset the local git repo to match origin/main.
    Captures stdout/stderr for later troubleshooting.
    """
    try:
        # fetch first (will also create origin if missing)
        subprocess.run(
            ["git", "fetch", "--all", "--prune"],
            cwd=SCRIPT_DIR,
            check=True,
            text=True,
        )
        # hard reset
        result = subprocess.run(
            ["git", "reset", "--hard", "origin/main"],
            cwd=SCRIPT_DIR,
            check=True,
            capture_output=True,
            text=True,
        )
        print("git reset output:\n", result.stdout, result.stderr)
    except Exception as exc:
        print(f"[launch.py] git update failed: {exc}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    online = wait_for_network()
    if online:
        update_repo()
    else:
        print("[launch.py] No network after timeout – skipping repo update")

    # always start the GUI (BLE provisioning works even without Internet)
    subprocess.Popen([str(VENV_PYTHON), str(GUI_SCRIPT)])
