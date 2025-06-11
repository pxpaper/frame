#!/usr/bin/env python3
"""
launch.py – updater + GUI bootstrapper for Pixel Paper
------------------------------------------------------
 • If Internet is up → pull public tarball → overlay files
 • Builds a venv that inherits system packages (bluezero, dbus)
 • Only runs pip installs when network_available == True
 • Exposes update_repo() so gui.py can trigger another overlay later
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
REQ_FILE     = os.path.join(SCRIPT_DIR, "requirements-frame.txt")  # optional

# ────────────────────────────────────────────────────────────────────────
def network_available(timeout=NETWORK_WAIT) -> bool:
    try:
        subprocess.run(
            ["nm-online", "--wait-for-startup", "--timeout", str(timeout)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False

def download_tarball(url=TARBALL_URL, dest=DOWNLOAD_TO):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    print(f"[update] downloading {url}")
    with urllib.request.urlopen(url, timeout=60) as r, open(dest, "wb") as o:
        shutil.copyfileobj(r, o)
    sz = os.path.getsize(dest)
    s256 = hashlib.sha256(open(dest, "rb").read()).hexdigest()[:12]
    print(f"[update] size={sz} sha256={s256}")
    return dest

def overlay_tarball(tar_path, dest_dir=SCRIPT_DIR):
    with tempfile.TemporaryDirectory(dir=os.path.dirname(tar_path)) as tdir:
        with tarfile.open(tar_path, "r:gz") as t:
            t.extractall(tdir)
        root = next(p for p in os.listdir(tdir)
                    if os.path.isdir(os.path.join(tdir, p)))
        src = os.path.join(tdir, root)
        subprocess.run(
            ["rsync", "-a", "--delete", "--exclude", "venv/",
             f"{src}/", f"{dest_dir}/"], check=True)
        print("[update] overlay complete")

def ensure_venv(create_only=False):
    if not os.path.exists(VENV_PY):
        print("[venv] creating (inherits system pkgs)")
        subprocess.run(
            [sys.executable, "-m", "venv", "--system-site-packages", VENV_DIR],
            check=True)
    if create_only:
        return

    pip = [VENV_PY, "-m", "pip", "install", "--no-deps"]  # skip dbus-python
    if os.path.exists(REQ_FILE):
        subprocess.run(pip + ["-r", REQ_FILE], check=True)
    else:
        subprocess.run(pip + ["bluezero"], check=True)
    print("[venv] packages ready")

# ── public helper so gui.py can trigger update once Wi-Fi is set up ─────
def update_repo():
    try:
        tp = download_tarball()
        overlay_tarball(tp)
    except Exception as err:
        print("[update_repo] failed:", err)

# ── MAIN ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    net = network_available()
    if net:
        try:
            update_repo()
        except Exception as e:
            print("[update] skipped (error)", e)
    else:
        print("[update] no network – deferring to BLE provisioning")

    # venv bootstrap (skip pip if no Internet)
    try:
        ensure_venv(create_only=not net)
        py = VENV_PY
    except Exception as e:
        print("[venv] error – using system python", e)
        py = sys.executable

    # start GUI
    subprocess.Popen([py, GUI_SCRIPT])
