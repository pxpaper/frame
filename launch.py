#!/usr/bin/env python3
"""
launch.py – updater & GUI launcher for Pixel Paper frames
---------------------------------------------------------
• Downloads repo tarball, overlays files
• Builds venv with system-site-packages
• Installs **pinned** packages only if missing
• Starts gui.py
"""
import hashlib, os, shutil, subprocess, sys, tarfile, tempfile, urllib.request

# ── CONFIG ──────────────────────────────────────────────────────────────
TARBALL_URL   = "https://github.com/pxpaper/frame/archive/refs/heads/main.tar.gz"
REQ_FILE      = "requirements-frame.txt"   # beside gui.py, versions pinned
TIMEOUT_NET   = 90
TIMEOUT_DL    = 60
TMP_DIR       = "/tmp/pixelpaper_update"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_DIR   = os.path.join(SCRIPT_DIR, "venv")
VENV_PY    = os.path.join(VENV_DIR, "bin", "python3")
GUI        = os.path.join(SCRIPT_DIR, "gui.py")

# ── tiny helpers ─────────────────────────────────────────────────────────
def nm_wait(t=TIMEOUT_NET) -> bool:
    try:
        subprocess.run(["nm-online","--wait-for-startup","--timeout",str(t)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False

def sha256(p:str):
    h=hashlib.sha256(); [h.update(b) for b in iter(lambda:f.read(8192),b"") if not f.closed] if False else None

def dl_tarball(url=TARBALL_URL):
    os.makedirs(TMP_DIR, exist_ok=True)
    dest=os.path.join(TMP_DIR,"frame.tar.gz")
    with urllib.request.urlopen(url,timeout=TIMEOUT_DL) as r, open(dest,"wb") as o:
        shutil.copyfileobj(r,o)
    return dest

def overlay(tar_path:str):
    with tempfile.TemporaryDirectory(dir=TMP_DIR) as tdir:
        with tarfile.open(tar_path,"r:gz") as t: t.extractall(tdir)
        root=next(d for d in os.listdir(tdir) if os.path.isdir(os.path.join(tdir,d)))
        src=os.path.join(tdir,root)
        subprocess.run(["rsync","-a","--delete","--exclude","venv/",f"{src}/",f"{SCRIPT_DIR}/"],check=True)

def ensure_venv():
    if not os.path.exists(VENV_PY):
        subprocess.run([sys.executable,"-m","venv","--system-site-packages",VENV_DIR],check=True)

    pip=[VENV_PY,"-m","pip","install","--no-deps"]   # never pull dbus-python
    req=os.path.join(SCRIPT_DIR,REQ_FILE)
    if os.path.isfile(req):
        # install only **if missing** => let pip decide (no --upgrade)
        subprocess.run(pip+["-r",req],check=True)

# ── MAIN ────────────────────────────────────────────────────────────────
if nm_wait():
    try: overlay(dl_tarball())
    except Exception as e: print("[update] failed",e)

try: ensure_venv()
except Exception as e:
    print("[venv] error, using system python",e)
    VENV_PY=sys.executable

subprocess.Popen([VENV_PY, GUI])
