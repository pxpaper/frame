#!/usr/bin/env python3
import subprocess
import time
import os

# Get the directory where launch.py resides.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Build the path to the virtual environment's python3 interpreter.
VENV_PYTHON = os.path.join(SCRIPT_DIR, "venv", "bin", "python3")

# Build the path to gui.py (assumed to be in the same directory as launch.py).
GUI_SCRIPT = os.path.join(SCRIPT_DIR, "gui.py")

def update_repo():
    try:
        # Fetch all changes from remote
        subprocess.run(
            ["git", "fetch", "--all"],
            cwd=SCRIPT_DIR,
            capture_output=True,
            text=True
        )
        # Force reset to match remote main branch
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

if __name__ == '__main__':
    time.sleep(10)  # Wait for the WiFi to be ready
    update_repo()
    # Launch the GUI application using the venv's python3 interpreter and the absolute path to gui.py.
    subprocess.Popen(["sudo", "-E", VENV_PYTHON, GUI_SCRIPT])