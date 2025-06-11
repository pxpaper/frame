#!/usr/bin/env python3
"""
launch.py – updater & GUI bootstrapper for Pixel Paper frames
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
• Downloads latest repo tarball (public URL)
• Rsync-overlays code (keeps venv/)
• Builds a virtual-env that inherits system packages
  – system provides `python3-dbus`, bluez, etc.
• Installs:
      1. bluezero  (with  --no-deps)
      2. everything in requirements-frame.txt  (normal pip)
• Starts gui.py with the venv interpreter (falls back to system Python)
"""

import hashlib, os, shutil, subprocess, sys, tarfile, tempfile, urllib.request

# ── USER-CONFIGURABLE ────────────────────────────────────────────────────
REPO_TAR_URL    = "https://github.com/pxpaper/frame/archive/refs/heads/main.tar.gz"
NETWORK_TIMEOUT = 90          # seconds nm-online may wait
DOWNLOAD_TIMEOUT= 60          # seconds urllib may wait
REQ_FILE        = "requirements-frame.txt"   # lives beside gui.py
TMP_BASE        = "/tmp/pixelpaper_update"

# ── paths ────────────────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))     # /opt/frame
VENV_DIR    = os.path.join(SCRIPT_DIR, "venv")
VENV_PY     = os.path.join(VENV_DIR,   "bin", "python3")
GUI_SCRIPT  = os.path.join(SCRIPT_DIR, "gui.py")

# ── helpers ──────────────────────────────────────────────────────────────
def wait_for_network(timeout=NETWORK_TIMEOUT) -> bool:
    try:
        subprocess.run(
            ["nm-online", "--wait-for-startup", "--timeout", str(timeout)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False

def sha256sum(p: str) -> str:
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for chunk in iter(lambda:f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def download_tar(url=REPO_TAR_URL) -> str:
    os.makedirs(TMP_BASE, exist_ok=True)
    local = os.path.join(TMP_BASE, "frame_latest.tar.gz")
    print(f"[update] downloading {url}")
    with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT) as r, open(local,"wb") as o:
        shutil.copyfileobj(r,o)
    print(f"[update] size={os.path.getsize(local)} sha256={sha256sum(local)[:12]}")
    return local

def overlay_tar(tar_path: str, dest=SCRIPT_DIR):
    with tempfile.TemporaryDirectory(dir=TMP_BASE) as tdir:
        print("[update] unpacking tarball")
        with tarfile.open(tar_path,"r:gz") as tar: tar.extractall(tdir)
        root = next(d for d in os.listdir(tdir) if os.path.isdir(os.path.join(tdir,d)))
        src  = os.path.join(tdir, root)
        print("[update] syncing files")
        subprocess.run(
            ["rsync","-a","--delete","--exclude","venv/",f"{src}/",f"{dest}/"],check=True)
        print("[update] overlay complete")

def ensure_venv():
    if not os.path.exists(VENV_PY):
        print("[venv] creating (inherits system pkgs)")
        subprocess.run([sys.executable,"-m","venv","--system-site-packages",VENV_DIR],check=True)

    pip = [VENV_PY,"-m","pip"]
    subprocess.run(pip+["install","--upgrade","pip"],check=True)

    # 1. bluezero without deps (skip dbus-python build)
    subprocess.run(pip+["install","--no-deps","--upgrade","bluezero"],check=True)

    # 2. other pure-Python deps from requirements-frame.txt
    req_path = os.path.join(SCRIPT_DIR, REQ_FILE)
    if os.path.isfile(req_path):
        subprocess.run(pip+["install","-r",req_path],check=True)

    print("[venv] packages ready")

# ── main ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if wait_for_network():
        try:
            tb = download_tar()
            overlay_tar(tb)
        except Exception as e:
            print(f"[update] FAILED – keeping previous build\n{e}")
    else:
        print("[update] network unavailable – skipping update")

    try:
        ensure_venv()
        py = VENV_PY
    except Exception as e:
        print(f"[venv] ERROR – using system Python\n{e}")
        py = sys.executable

    print("[gui] launching GUI")
    subprocess.Popen([py, GUI_SCRIPT])
