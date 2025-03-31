#!/usr/bin/env python3
import os
import stat
import subprocess
import time

def update_repo():
    try:
        # Pull the latest changes from GitHub
        result = subprocess.run(["git", "pull"], capture_output=True, text=True)
        print("STDOUT:\n", result.stdout)
        print("STDERR:\n", result.stderr)
    except Exception as e:
        print(f"Error updating repository: {e}")

if __name__ == '__main__':
    time.sleep(10) 
    update_repo()

# oop