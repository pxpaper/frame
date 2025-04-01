#!/usr/bin/env python3
import subprocess
import time
import os

# Build the path to the virtual environment's python3 interpreter.
VENV_PYTHON = os.path.join(os.getcwd(), "venv", "bin", "python3")

def update_repo():
    try:
        # Pull the latest changes from GitHub
        result = subprocess.run(["git", "pull"], capture_output=True, text=True)
        print("STDOUT:\n", result.stdout)
        print("STDERR:\n", result.stderr)
    except Exception as e:
        print(f"Error updating repository: {e}")

if __name__ == '__main__':
    time.sleep(10)  # Wait for the WiFi to be ready
    update_repo()
    # Launch the GUI application using the venv's python interpreter
    subprocess.Popen([VENV_PYTHON, "gui.py"])
