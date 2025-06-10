#!/usr/bin/env python3
"""
Pixel Paper – UI + provisioning GUI
───────────────────────────────────
• ttkbootstrap for full-screen status & toasts
• Original Bluezero GATT logic, but guarded so the
  object-path handler is never registered twice.
"""

from __future__ import annotations
import os, socket, subprocess, threading, time, sys
import tkinter.font as tkfont
from typing import Optional, List

# ── third-party ──────────────────────────────────────────────────────────
import ttkbootstrap as ttk
from ttkbootstrap.toast import ToastNotification
from bluezero import adapter, peripheral
from dbus.exceptions import DBusException   # type: ignore

# ── local helper ─────────────────────────────────────────────────────────
import launch  # update_repo()  and get_serial_number()

# ───── palette ───────────────────────────────────────────────────────────
CLR_BG   = "#010101"
CLR_ACC  = "#1FC742"
CLR_TEXT = "#E8E8E8"

# ───── toast helper ──────────────────────────────────────────────────────
_STACK: List[ToastNotification] = []
STEP = 70

def _toast(msg: str, style: str = "success"):
    y = 20 + len(_STACK)*STEP
    t = ToastNotification("Pixel Paper", msg, 3500, style, (20, y, 'ne'))
    _STACK.append(t)
    t.show_toast()
    root.after(3800, lambda: _STACK.remove(t) if t in _STACK else None)

def log_debug(msg: str):
    print(msg, file=sys.stderr, flush=True)
    root.after(0, _toast, msg)

# ───── BLE UUIDs ─────────────────────────────────────────────────────────
PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"
SERIAL_CHAR_UUID          = "12345678-1234-5678-1234-56789abcdef2"

# ───── Wi-Fi helpers ─────────────────────────────────────────────────────
def check_wifi_connection(retries: int = 2) -> bool:
    for _ in range(retries):
        try:
            s = socket.create_connection(("8.8.8.8", 53), timeout=2); s.close()
            return True
        except OSError:
            time.sleep(0.25)
    return False

def nm_reconnect():
    try:
        ssid = subprocess.check_output(
            ["nmcli", "-t", "-f", "NAME,TYPE,DEVICE,ACTIVE",
             "connection", "show", "--active"], text=True
        ).split(':')[0]
        subprocess.run(["nmcli","connection","up",ssid], check=False)
        log_debug(f"nmcli reconnect issued for {ssid}")
    except Exception as e:
        log_debug(f"nm_reconnect err: {e}")

# ───── Chromium watchdog ─────────────────────────────────────────────────
chromium_proc: Optional[subprocess.Popen] = None
repo_done   = False
fails       = 0
FAIL_MAX    = 3

def update_status():
    global chromium_proc, repo_done, fails
    if check_wifi_connection():
        status_lbl.configure(text="Connected ✓", foreground=CLR_ACC)
        fails = 0
        if not repo_done:
            threading.Thread(target=launch.update_repo, daemon=True).start()
            repo_done = True
        if chromium_proc is None or chromium_proc.poll() is not None:
            url = f"https://pixelpaper.com/frame.html?id={launch.get_serial_number()}"
            subprocess.run(["pkill","-f","chromium"], check=False)
            chromium_proc = subprocess.Popen(["chromium","--kiosk",url])
            log_debug("Chromium (re)started.")
    else:
        if fails < FAIL_MAX:
            fails += 1
            status_lbl.configure(text="Waiting for Wi-Fi…", foreground=CLR_TEXT)
        else:
            status_lbl.configure(text="Offline ⚠", foreground="#ff9933")
            nm_reconnect()
    root.after(3_000, update_status)

# ───── provisioning handlers (unchanged) ─────────────────────────────────
def handle_wifi_data(payload:str): ...
def handle_orientation_change(data:str): ...
def ble_callback(value, options): ...

# ───── fixed-lifetime GATT server ────────────────────────────────────────
def run_gatt_server():
    periph: peripheral.Peripheral | None = None
    while True:
        try:
            dongles = adapter.Adapter.available()
            if not dongles:
                log_debug("No BLE adapters; retry in 5 s.")
                time.sleep(5); continue
            addr = list(dongles)[0].address

            # tear down previous instance (if any) *cleanly*
            if periph is not None:
                try:
                    periph.unpublish()      # Bluezero ≥0.7
                except AttributeError:
                    try: periph.quit()      # Bluezero ≤0.6
                    except Exception: pass
                periph = None
                time.sleep(0.5)            # let DBus settle

            periph = peripheral.Peripheral(addr, local_name="PixelPaper")
            periph.add_service(1, PROVISIONING_SERVICE_UUID, True)

            periph.add_characteristic(
                1, 1, PROVISIONING_CHAR_UUID,
                value=[], notifying=False,
                flags=['write','write-without-response'],
                write_callback=ble_callback)

            periph.add_characteristic(
                1, 2, SERIAL_CHAR_UUID,
                value=list(launch.get_serial_number().encode()),
                notifying=False, flags=['read'],
                read_callback=lambda _:
                    list(launch.get_serial_number().encode())
            )

            log_debug("Publishing GATT provisioning service…")
            periph.publish()               # registers on DBus
            log_debug("GATT service active.")
            while True:                    # keep thread alive
                time.sleep(60)

        except DBusException as e:
            log_debug(f"GATT/DBus error: {e}. Restarting in 5 s.")
            time.sleep(5)
        except Exception as e:
            log_debug(f"GATT server error: {e}. Restarting in 5 s.")
            time.sleep(5)

def start_gatt_thread():
    threading.Thread(target=run_gatt_server, daemon=True).start()

def disable_pairing():
    try:
        subprocess.run(["bluetoothctl"],
            input="pairable no\nquit\n", text=True,
            capture_output=True, check=True)
    except Exception as e:
        log_debug("Failed to disable pairing: "+str(e))

# ───── UI setup (tk + ttkbootstrap) ──────────────────────────────────────
root = ttk.Window(themename="darkly")
root.title("Pixel Paper – Setup")
root.configure(bg=CLR_BG)
root.attributes('-fullscreen', True)
root.bind("<Escape>", lambda e: None)

status_font = tkfont.Font(family="Helvetica", size=64, weight="bold")
status_lbl  = ttk.Label(root, text="Checking Wi-Fi…",
                        foreground=CLR_TEXT, background=CLR_BG,
                        font=status_font)
status_lbl.pack(expand=True)

root.bind("<Configure>",
          lambda e: status_font.configure(
              size=max(root.winfo_width(), root.winfo_height())//18))

# ───── boot sequence ─────────────────────────────────────────────────────
disable_pairing()
start_gatt_thread()
root.after(200, update_status)
root.mainloop()
