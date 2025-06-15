#!/usr/bin/env python3
"""
launch.py – updater + GUI bootstrapper for Pixel Paper
------------------------------------------------------
 • If Internet is up → pull public tarball → overlay files
 • Assumes a pre-existing python venv with all packages.
"""

import hashlib, os, shutil, subprocess, sys, tarfile, tempfile, urllib.request

# ── CONFIG ────────────────────────────────────────────────────────────
TARBALL_URL = "https://github.com/pxpaper/frame/archive/refs/heads/main.tar.gz"
NETWORK_WAIT = 90         # seconds nm-online may wait
DOWNLOAD_TO  = "/tmp/pixelpaper_update/frame.tar.gz"
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
VENV_DIR     = os.path.join(SCRIPT_DIR, "venv")
VENV_PY      = os.path.join(VENV_DIR, "bin", "python3")
GUI_SCRIPT   = os.path.join(SCRIPT_DIR, "gui.py")

# ────────────────────────────────────────────────────────────────────────
def network_available(timeout=NETWORK_WAIT) -> bool:
    """Checks for a live internet connection."""
    try:
        subprocess.run(
            ["nm-online", "--wait-for-startup", "--timeout", str(timeout)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False

def download_tarball(url=TARBALL_URL, dest=DOWNLOAD_TO):
    """Downloads the release tarball to a destination."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    print(f"[update] downloading {url}")
    with urllib.request.urlopen(url, timeout=60) as r, open(dest, "wb") as o:
        shutil.copyfileobj(r, o)
    sz = os.path.getsize(dest)
    s256 = hashlib.sha256(open(dest, "rb").read()).hexdigest()[:12]
    print(f"[update] size={sz} sha256={s256}")
    return dest

def overlay_tarball(tar_path, dest_dir=SCRIPT_DIR):
    """Extracts and overlays files using rsync."""
    with tempfile.TemporaryDirectory(dir=os.path.dirname(tar_path)) as tdir:
        with tarfile.open(tar_path, "r:gz") as t:
            t.extractall(tdir)
        # Find the root directory inside the tarball (e.g., 'frame-main')
        root = next(p for p in os.listdir(tdir)
                    if os.path.isdir(os.path.join(tdir, p)))
        src = os.path.join(tdir, root)
        subprocess.run(
            ["rsync", "-a", "--delete", "--exclude", "venv/",
             f"{src}/", f"{dest_dir}/"], check=True)
        print("[update] overlay complete")

def update_repo():
    """Public helper to download and overlay the repo."""
    try:
        tarball_path = download_tarball()
        overlay_tarball(tarball_path)
    except Exception as err:
        print(f"[update_repo] failed: {err}")

# ── MAIN ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if network_available():
        try:
            print("[update] network available, checking for updates...")
            update_repo()
        except Exception as e:
            print(f"[update] skipped due to an error: {e}")
    else:
        print("[update] no network – launching GUI directly")

    # Determine which python executable to use as a fallback.
    py_executable = VENV_PY if os.path.exists(VENV_PY) else sys.executable
    if py_executable == sys.executable:
        print("[launcher] WARNING: venv not found, using system python.")

    # Start the GUI script.
    print(f"[launcher] starting gui.py using {os.path.basename(py_executable)}")
    subprocess.Popen([py_executable, GUI_SCRIPT])