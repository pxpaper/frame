#!/usr/bin/env python3
"""
Pixel Paper – redesigned GUI
────────────────────────────
 • Full-screen, brand-coloured status screen (portrait or landscape)
 • Smooth, self-scaling typography
 • Toast messages (top-right) instead of a fixed debug panel
 • All original logic (BLE, Wi-Fi, kanshi, chromium …) unchanged
"""
import tkinter as tk
import tkinter.font as tkfont
import time
import socket
import subprocess
import threading
import os

from bluezero import adapter, peripheral
import launch          # ← for update_repo(), get_serial_number() lives here

# ── brand palette ─────────────────────────────────────────────────────────
CLR_BG      = "#010101"   # nearly-black background
CLR_ACCENT  = "#1FC742"   # bright accent green
CLR_ACCENT2 = "#025B18"   # dark accent
CLR_TEXT    = "#E8E8E8"   # light grey for text

# ── global state ─────────────────────────────────────────────────────────
toast_stack   : list["Toast"] = []   # active toast objects
chromium_proc : subprocess.Popen | None = None
repo_updated  = False
fail_count    = 0
FAIL_MAX      = 3

# BLE UUIDs (unchanged)
PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"
SERIAL_CHAR_UUID          = "12345678-1234-5678-1234-56789abcdef2"

# ── helpers – UI ──────────────────────────────────────────────────────────
class Toast:
    """Ephemeral message that slides in and auto-fades."""
    WIDTH   = 380
    PAD     = 12
    SLIDE_MS = 250
    ALIVE_MS = 4_000
    FADE_MS  = 400

    def __init__(self, master: tk.Frame, message: str):
        self.master = master
        self.frame  = tk.Frame(master, bg=CLR_ACCENT2, bd=0, highlightthickness=0)
        lbl = tk.Label(self.frame, text=message,
                       fg=CLR_TEXT, bg=CLR_ACCENT2, justify="left",
                       wraplength=self.WIDTH - 2*self.PAD)
        lbl.pack(padx=self.PAD, pady=(self.PAD, self.PAD-2), anchor="w")
        self.frame.update_idletasks()
        h = self.frame.winfo_height()
        y = 20 + sum(t.frame.winfo_height() + 10 for t in toast_stack)
        self.frame.place(relx=1.0, x=self.WIDTH+20, y=y, anchor="ne")
        toast_stack.append(self)
        self._slide_in()
        self.master.after(self.ALIVE_MS, self._fade_and_destroy)

    def _slide_in(self):
        steps = int(self.SLIDE_MS / 16)
        dx = (self.WIDTH + 20) / steps
        def step(i=0):
            if i < steps:
                self.frame.place_configure(x=-(dx*i))
                self.master.after(16, step, i+1)
        step()

    def _fade_and_destroy(self):
        steps = int(self.FADE_MS / 50)
        def fade(op=1.0):
            if op <= 0:
                self.frame.destroy()
                toast_stack.remove(self)
                _reflow_toasts()
                return
            c_bg = _fade_hex(CLR_ACCENT2, op)
            c_fg = _fade_hex(CLR_TEXT, op)
            self.frame.config(bg=c_bg)
            for w in self.frame.winfo_children():
                w.config(bg=c_bg, fg=c_fg)
            self.master.after(50, fade, op - (1/steps))
        fade()

def _fade_hex(hex_color: str, factor: float) -> str:
    r = int(int(hex_color[1:3],16) * factor)
    g = int(int(hex_color[3:5],16) * factor)
    b = int(int(hex_color[5:7],16) * factor)
    return f"#{r:02x}{g:02x}{b:02x}"

def _reflow_toasts():
    y = 20
    for t in toast_stack:
        t.frame.place_configure(y=y)
        y += t.frame.winfo_height() + 10

def log_debug(msg: str):
    print(msg)
    root.after(0, Toast, root, msg)

# ── networking helpers (unchanged logic, small tweaks) ───────────────────
def check_wifi_connection(retries: int = 2) -> bool:
    for _ in range(retries):
        try:
            s = socket.create_connection(("8.8.8.8", 53), timeout=2)
            s.close()
            return True
        except OSError:
            time.sleep(0.25)
    return False

def nm_reconnect():
    try:
        ssid = subprocess.check_output(
            ["nmcli","-t","-f","NAME,TYPE,DEVICE,ACTIVE","connection","show","--active"],
            text=True
        ).split(':')[0]
        subprocess.run(["nmcli","connection","up",ssid], check=False)
        log_debug(f"nmcli reconnect issued for {ssid}")
    except Exception as e:
        log_debug(f"nm_reconnect err: {e}")

# ── main status update loop ───────────────────────────────────────────────
def update_status():
    global chromium_proc, fail_count, repo_updated
    up = check_wifi_connection()
    if up:
        status_lbl.config(text="Connected ✓", fg=CLR_ACCENT)
        if fail_count: fail_count = 0
        if not repo_updated:
            threading.Thread(target=launch.update_repo, daemon=True).start()
            repo_updated = True
        if chromium_proc is None or chromium_proc.poll() is not None:
            url = f"https://pixelpaper.com/frame.html?id={launch.get_serial_number()}"
            subprocess.run(["pkill","-f","chromium"], check=False)
            chromium_proc = subprocess.Popen(["chromium","--kiosk",url])
    else:
        if fail_count < FAIL_MAX:
            fail_count += 1
            status_lbl.config(text="Waiting for Wi-Fi…", fg=CLR_TEXT)
        else:
            status_lbl.config(text="Offline ⚠", fg="#ff9933")
            nm_reconnect()
    root.after(3_000, update_status)

# ── BLE / provisioning / kanshi rotation – original code ─────────────────
provisioning_char = None
def handle_wifi_data(data):            ...existing code...
def handle_orientation_change(data):   ...existing code...
def ble_callback(value,options):       ...existing code...
def start_gatt_server():               ...existing code...
def start_gatt_thread():               ...existing code...

# ── tkinter initialisation ───────────────────────────────────────────────
root = tk.Tk()
root.title("Pixel Paper-Frame")
root.configure(bg=CLR_BG)
root.attributes('-fullscreen', True)
root.bind("<Escape>", lambda e: None)  # disable ESC

status_font = tkfont.Font(family="Helvetica", size=64, weight="bold")
status_lbl  = tk.Label(root, text="Checking Wi-Fi…",
                       fg=CLR_TEXT, bg=CLR_BG, font=status_font)
status_lbl.pack(expand=True)

def _autoscale(event=None):
    size = max(root.winfo_width(), root.winfo_height()) // 18
    status_font.configure(size=size)
root.bind("<Configure>", _autoscale)

# ── startup ──────────────────────────────────────────────────────────────
disable_pairing()
start_gatt_thread()
root.after(200, update_status)
root.mainloop()