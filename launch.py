#!/usr/bin/env python3
"""
launch.py – updater & GUI launcher for Pixel Paper frames
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
• Waits (≤90 s) for Internet
• Downloads repo snapshot tarball (public URL – no creds)
• Rsync-overlays new files (leaves venv/ intact)
• Ensures a venv that *inherits system site-packages* and has Bluezero
  (dbus bindings come from the OS, so no wheel compilation)
• Starts gui.py with that venv’s Python (falls back to system Python)
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
)
DOWNLOAD_TIMEOUT = 60          # seconds
NETWORK_TIMEOUT  = 90          # seconds to wait for connectivity

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))   # /opt/frame
VENV_DIR   = os.path.join(SCRIPT_DIR, "venv")
VENV_PY    = os.path.join(VENV_DIR, "bin", "python3")
GUI_SCRIPT = os.path.join(SCRIPT_DIR, "gui.py")

TMP_BASE   = "/tmp/pixelpaper_update"
PIP_FLAGS  = ["--no-deps", "--upgrade"]    # skip dbus-python dep chain
BLUEZERO   = "bluezero"

# ── helpers ──────────────────────────────────────────────────────────────
def wait_for_network(timeout: int = NETWORK_TIMEOUT) -> bool:
    try:
        subprocess.run(
            ["nm-online", "--wait-for-startup", "--timeout", str(timeout)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
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

    print(f"[update] size={os.path.getsize(local)} sha256={sha256sum(local)[:12]}")
    return local


def overlay_tarball(tar_path: str, dest_dir: str = SCRIPT_DIR) -> None:
    with tempfile.TemporaryDirectory(dir=TMP_BASE) as tdir:
        print("[update] unpacking tarball")
        with tarfile.open(tar_path, "r:gz") as tar:
            tar.extractall(path=tdir)

        root = next(p for p in os.listdir(tdir) if os.path.isdir(os.path.join(tdir, p)))
        src  = os.path.join(tdir, root)

        print("[update] syncing files → live dir")
        subprocess.run(
            ["rsync", "-a", "--delete", "--exclude", "venv/", f"{src}/", f"{dest_dir}/"],
            check=True,
        )
        print("[update] overlay complete")


def ensure_venv() -> None:
    """Create venv (inherits system pkgs) and install / upgrade Bluezero."""
    if not os.path.exists(VENV_PY):
        print("[venv] creating virtual-env with system site-packages")
        subprocess.run(
            [sys.executable, "-m", "venv", "--system-site-packages", VENV_DIR],
            check=True,
        )

    pip = [VENV_PY, "-m", "pip"]
    subprocess.run(pip + ["install", "--upgrade", "pip"], check=True)

    # install Bluezero but *skip* building dbus-python
    subprocess.run(pip + ["install", *PIP_FLAGS, BLUEZERO], check=True)
    print("[venv] bluezero ready (dbus from system pkg)")


# ── MAIN ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if wait_for_network():
        try:
            tb = download_tarball()
            overlay_tarball(tb)
        except Exception as exc:
            print(f"[update] FAILED – keeping previous build\n{exc}")
    else:
        print("[update] network unavailable – skipping update")

    try:
        ensure_venv()
        python_bin = VENV_PY
    except Exception as exc:
        print(f"[venv] ERROR – using system Python\n{exc}")
        python_bin = sys.executable

    print("[gui] launching GUI")
    subprocess.Popen([python_bin, GUI_SCRIPT])
