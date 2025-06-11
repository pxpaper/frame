#!/usr/bin/env python3
"""
launch.py – updater & GUI launcher for Pixel Paper frames
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* Waits until Internet is up (max 90 s)
* Downloads the latest snapshot of the public GitHub repo (tarball)
* Atomically overlays new files onto the live install dir (leaves venv/ intact)
* Ensures a virtual-env exists **and has both `bluezero` _and_ `dbus-python`**
* Starts the GUI with the venv’s Python (falls back to system Python if needed)

No credentials, no .git directory, minimal chance of corruption.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

# ── CONFIG ──────────────────────────────────────────────────────────────
REPO_TARBALL_URL = (
    "https://github.com/pxpaper/frame/archive/refs/heads/main.tar.gz"
)                           # public URL (adjust if your branch/owner changes)
DOWNLOAD_TIMEOUT = 60       # seconds
NETWORK_TIMEOUT  = 90       # seconds to wait for Internet

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))  # /opt/frame
VENV_DIR   = os.path.join(SCRIPT_DIR, "venv")
VENV_PY    = os.path.join(VENV_DIR, "bin", "python3")
GUI_SCRIPT = os.path.join(SCRIPT_DIR, "gui.py")

TMP_BASE   = "/tmp/pixelpaper_update"

# Python packages the GUI needs
PIP_PKGS   = ["bluezero", "dbus-python"]   # <-- NEW: dbus bindings

# ── helpers ──────────────────────────────────────────────────────────────
def wait_for_network(timeout: int = NETWORK_TIMEOUT) -> bool:
    try:
        subprocess.run(
            ["nm-online", "--wait-for-startup", "--timeout", str(timeout)],
            check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return True
    except FileNotFoundError:
        return True              # nm-online not available; carry on
    except subprocess.CalledProcessError:
        return False


def sha256sum(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def download_tarball(url: str = REPO_TARBALL_URL) -> str:
    os.makedirs(TMP_BASE, exist_ok=True)
    local = os.path.join(TMP_BASE, "frame_latest.tar.gz")

    print(f"[update] downloading {url}")
    with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT) as resp, open(local, "wb") as out:
        shutil.copyfileobj(resp, out)
    print(f"[update] size={os.path.getsize(local)}  sha256={sha256sum(local)[:12]}")
    return local


def unpack_and_overlay(tar_path: str, dest_dir: str = SCRIPT_DIR) -> None:
    with tempfile.TemporaryDirectory(dir=TMP_BASE) as tdir:
        print("[update] unpacking tarball")
        with tarfile.open(tar_path, "r:gz") as tar:
            tar.extractall(path=tdir)

        root = next(p for p in os.listdir(tdir) if os.path.isdir(os.path.join(tdir, p)))
        src  = os.path.join(tdir, root)

        print("[update] syncing new files → live dir")
        subprocess.run(
            ["rsync", "-a", "--delete", "--exclude", "venv/", f"{src}/", f"{dest_dir}/"],
            check=True
        )
        print("[update] overlay complete")


def ensure_venv() -> None:
    """Create venv & install/upgrade required packages if missing."""
    # 1. Create venv if needed
    if not os.path.exists(VENV_PY):
        print("[venv] creating virtual-env")
        subprocess.run([sys.executable, "-m", "venv", VENV_DIR], check=True)

    # 2. Upgrade pip & install/upgrade packages
    pip_cmd = [VENV_PY, "-m", "pip"]
    subprocess.run(pip_cmd + ["install", "--upgrade", "pip", *PIP_PKGS], check=True)
    print("[venv] dependencies up-to-date")


# ── MAIN ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if wait_for_network():
        try:
            tarball = download_tarball()
            unpack_and_overlay(tarball)
        except Exception as exc:
            print(f"[update] FAILED – keeping previous build\n{exc}")
    else:
        print("[update] network unavailable – skipping update")

    # venv bootstrap (creates & installs bluezero + dbus-python)
    try:
        ensure_venv()
        python_bin = VENV_PY
    except Exception as exc:
        print(f"[venv] ERROR – using system Python\n{exc}")
        python_bin = sys.executable

    print("[gui] launching GUI")
    subprocess.Popen([python_bin, GUI_SCRIPT])
