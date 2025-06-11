#!/usr/bin/env python3
"""
gui.py – Pixel Paper frame GUI
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
• Full-screen status window (black background, green text)
• BLE GATT server for provisioning
• Wi-Fi watchdog → launches Chromium kiosk
• Toast notifications via ttkbootstrap
Everything is now ttkbootstrap-native; no plain-Tk widgets remain.
"""
import os, socket, subprocess, threading, time, queue

from bluezero import adapter, peripheral
import ttkbootstrap as tb
from ttkbootstrap import ttk               # ← NEW: ttkbootstrap widgets
from ttkbootstrap.toast import ToastNotification

import launch                              # repo-update helper

# ── Globals ────────────────────────────────────────────────────────────────
provisioning_char = None
chromium_process  = None
repo_updated      = False
fail_count        = 0

PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"
SERIAL_CHAR_UUID          = "12345678-1234-5678-1234-56789abcdef2"

# toast queue
toast_q          = queue.SimpleQueue()
_toast_visible   = False

# ── Toast helpers ─────────────────────────────────────────────────────────
def _show_next_toast():
    global _toast_visible
    if _toast_visible or toast_q.empty():
        return

    _toast_visible = True
    msg = toast_q.get()

    class SmoothToast(ToastNotification):
        def hide_toast(self, *_):
            try:
                a = float(self.toplevel.attributes("-alpha"))
                if a <= 0.02:
                    self.toplevel.destroy()
                    fin()
                else:
                    self.toplevel.attributes("-alpha", a - 0.02)
                    self.toplevel.after(25, self.hide_toast)
            except Exception:
                self.toplevel.destroy()
                fin()

    def fin():
        global _toast_visible
        _toast_visible = False
        root.after_idle(_show_next_toast)

    SmoothToast(
        title="Pixel Paper",
        message=msg,
        bootstyle="info",           # our green (#1FC742)
        duration=3000,
        position=(10, 10, "ne"),
        alpha=0.95
    ).show_toast()

def log_debug(msg: str):
    toast_q.put(msg)
    try:
        root.after_idle(_show_next_toast)
    except NameError:
        pass
    print(msg)

# ── Utility functions ─────────────────────────────────────────────────────
def get_serial() -> str:
    try:
        with open('/proc/device-tree/serial-number') as f:
            return "PX" + f.read().strip('\x00\n ')
    except Exception:
        return "PXunknown"

def check_wifi(retries=2) -> bool:
    for _ in range(retries):
        try:
            s=socket.create_connection(("8.8.8.8",53),timeout=3); s.close(); return True
        except OSError:
            time.sleep(0.3)
    return False

# ── Wi-Fi / Chromium status loop ──────────────────────────────────────────
def update_status():
    global chromium_process, fail_count, repo_updated
    try:
        up = check_wifi()
        if up:
            if fail_count:
                fail_count = 0
                if not repo_updated:
                    threading.Thread(target=launch.wait_for_network, daemon=True).start()
                    repo_updated = True

            if chromium_process is None or chromium_process.poll() is not None:
                status_lbl.configure(text="Wi-Fi Connected")
                subprocess.run(["pkill", "-f", "chromium"], check=False)
                url = f"https://pixelpaper.com/frame.html?id={get_serial()}"
                chromium_process = subprocess.Popen(["chromium","--kiosk",url])
        else:
            fail_count += 1
            if fail_count == 1:
                status_lbl.configure(text="Wi-Fi Lost – reconnecting…")
    except Exception as e:
        log_debug(f"update_status error: {e}")
    finally:
        root.after(2000, update_status)   # schedule next check

# ── BLE callbacks ─────────────────────────────────────────────────────────
def handle_wifi_data(payload: str):
    try:
        ssid, pass_part = payload.split(';',1)
        pwd  = pass_part.split(':',1)[1]
    except ValueError:
        log_debug("Wi-Fi payload malformed")
        return

    subprocess.run(["nmcli","connection","delete","id",ssid], check=False)
    subprocess.run([
        "nmcli","connection","add","type","wifi","ifname","wlan0",
        "con-name",ssid,"ssid",ssid,
        "wifi-sec.key-mgmt","wpa-psk","wifi-sec.psk",pwd,
        "802-11-wireless-security.psk-flags","0","connection.autoconnect","yes"
    ], check=True)
    subprocess.run(["nmcli","connection","up",ssid], check=True)
    log_debug(f"Connected to {ssid}")

def handle_orientation_change(t: str):
    orient = "Portrait" if t in ("90","270") else "Landscape"
    log_debug(orient)

def ble_cb(value, _opts):
    try:
        if value is None: return
        msg = (bytes(value) if isinstance(value, list) else value).decode().strip()
        if msg.startswith("WIFI:"):
            handle_wifi_data(msg[5:].strip())
        elif msg.startswith("ORIENT:"):
            handle_orientation_change(msg[7:].strip())
        elif msg == "REBOOT":
            log_debug("Rebooting…")
            subprocess.run(["sudo","reboot"])
    except Exception as e:
        log_debug(f"BLE error: {e}")

# ── GATT server thread ────────────────────────────────────────────────────
def gatt_server():
    global provisioning_char
    while True:
        try:
            dongles = adapter.Adapter.available()
            if not dongles:
                log_debug("No BLE adapter!")
                time.sleep(5); continue
            addr = list(dongles)[0].address
            periph = peripheral.Peripheral(addr, local_name="PixelPaper")
            periph.add_service(1, PROVISIONING_SERVICE_UUID, primary=True)
            provisioning_char = periph.add_characteristic(
                1, 1, PROVISIONING_CHAR_UUID, value=[],
                notifying=False, flags=["write","write-without-response"],
                write_callback=ble_cb
            )
            periph.add_characteristic(
                1, 2, SERIAL_CHAR_UUID,
                value=list(get_serial().encode()),
                notifying=False, flags=['read'],
                read_callback=lambda _o: list(get_serial().encode())
            )
            periph.publish()
        except Exception as e:
            log_debug(f"GATT error: {e}")
        log_debug("Restarting GATT in 5 s")
        time.sleep(5)

# ── Main GUI ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tb.Window(themename="litera")
    GREEN = "#1FC742"

    # Global theme tweaks
    root.style.colors.set("info", GREEN)
    root.style.configure("TFrame", background="black")
    root.style.configure("Status.TLabel",
                         background="black", foreground=GREEN,
                         font=("Helvetica", 48))

    root.title("Frame Status")
    root.attributes("-fullscreen", True)
    root.configure(background="black")
    root.bind("<Escape>", lambda e: root.attributes("-fullscreen", False))

    status_lbl = ttk.Label(root, text="Checking Wi-Fi…", style="Status.TLabel")
    status_lbl.pack(expand=True)

    # Start background pieces
    threading.Thread(target=gatt_server, daemon=True).start()
    update_status()                    # first Wi-Fi / Chromium check

    root.mainloop()
