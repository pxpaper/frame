#!/usr/bin/env python3
import subprocess
import os
import sys

# ── paths ────────────────────────────────────────────────────────────────
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
VENV_PYTHON  = os.path.join(SCRIPT_DIR, "venv", "bin", "python3")
GUI_SCRIPT   = os.path.join(SCRIPT_DIR, "gui.py")

# ── helpers ──────────────────────────────────────────────────────────────
def wait_for_network(timeout=90) -> bool:
    """
    Block until NetworkManager reports a working Internet connection
    or the timeout elapses.  Uses nm‑online if available.
    """
    try:
        subprocess.run(
            ["nm-online", "--wait-for-startup", "--timeout", str(timeout)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except FileNotFoundError:
        # nm-online not installed – skip the wait
        return False
    except subprocess.CalledProcessError:
        # Timed out – no connectivity
        return False

def update_repo():
    try:
        # 1. fetch everything
        subprocess.run(
            ["git", "fetch", "--all"],
            cwd=SCRIPT_DIR,
            capture_output=True,
            text=True
        )
        # 2. hard‑reset to origin/main
        result = subprocess.run(
            ["git", "reset", "--hard", "origin/main"],
            cwd=SCRIPT_DIR,
            capture_output=True,
            text=True
        )
        print("STDOUT:\n", result.stdout)
        print("STDERR:\n", result.stderr)
    except Exception as e:
        print(f"Error updating repository: {e}")

# ── main ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if wait_for_network():
        update_repo()
    else:
        print("Network unavailable – skipping repo update this boot.")

    # always start the GUI (Bluetooth provisioning may be needed)
    subprocess.Popen([VENV_PYTHON, GUI_SCRIPT])
