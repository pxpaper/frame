#!/usr/bin/env python3
import os
import stat
import subprocess

# Automatically set the executable bit on this file.
# 0o755 means: owner read/write/execute, group and others read/execute.
current_file = os.path.realpath(__file__)
os.chmod(current_file, 0o755)

def update_repo():
    try:
        # Pull the latest changes from GitHub
        result = subprocess.run(["git", "pull"], capture_output=True, text=True)
        print("STDOUT:\n", result.stdout)
        print("STDERR:\n", result.stderr)
    except Exception as e:
        print(f"Error updating repository: {e}")

if __name__ == '__main__':
    update_repo()

#hello