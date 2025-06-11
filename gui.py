#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pixel Paper frame launcher
──────────────────────────
 • Bluetooth GATT: receive Wi-Fi creds + orientation commands
 • Periodically check Wi-Fi; when online, update repo & launch Chromium
 • Full-screen Tk status window with green-on-black text + loading spinner
 • Toast notifications (top-right), queued & thread-safe
"""

import os, queue, socket, subprocess, threading, time
import tkinter as tk
from ttkbootstrap import ttk
import ttkbootstrap as tb
from ttkbootstrap.toast import ToastNotification
from bluezero import adapter, peripheral

import launch   # your own module

# ───────────────────────────── Globals ──────────────────────────────
chromium_process = None
repo_updated     = False
fail_count       = 0
toast_queue      = queue.SimpleQueue()
_toast_active    = False
GREEN            = "#1FC742"

# BLE UUIDs
PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"
SERIAL_CHAR_UUID          = "12345678-1234-5678-1234-56789abcdef2"


# ─────────────────────── Toast infrastructure ──────────────────────
def _show_next_toast():
    global _toast_active
    if _toast_active or toast_queue.empty():
        return

    _toast_active = True
    msg = toast_queue.get()

    class SmoothToast(ToastNotification):
        def hide_toast(self, *_):
            try:
                a = float(self.toplevel.attributes("-alpha"))
                if a <= 0.02:
                    self.toplevel.destroy()
                    finish()
                else:
                    self.toplevel.attributes("-alpha", a - 0.02)
                    self.toplevel.after(25, self.hide_toast)
            except Exception:
                self.toplevel.destroy()
                finish()

    def finish():
        global _toast_active
        _toast_active = False
        root.after_idle(_show_next_toast)

    SmoothToast(
        title="Pixel Paper",
        message=msg,
        bootstyle="info",
        duration=3000,
        position=(10, 10, "ne"),
        alpha=0.95
    ).show_toast()


def log_debug(msg: str):
    toast_queue.put(msg)
    try:
        root.after_idle(_show_next_toast)
    except NameError:
        pass
    print(msg)


# ───────────────────────── Utility helpers ─────────────────────────
def get_serial_number() -> str:
    try:
        with open('/proc/device-tree/serial-number') as f:
            return "PX" + f.read().strip('\x00\n ')
    except Exception:
        return "PXunknown"


def check_wifi_connection(tries: int = 2) -> bool:
    for _ in range(tries):
        try:
            sock = socket.create_connection(("8.8.8.8", 53), 3)
            sock.close()
            return True
        except OSError:
            time.sleep(0.3)
    return False


# ───────────────────────── BLE callbacks ───────────────────────────
def handle_wifi_data(payload: str):
    """Create/replace a single NM profile with stored PSK."""
    try:
        ssid, pwd = payload.split(';', 1)[0], payload.split(':', 1)[1]
    except ValueError:
        log_debug("Wi-Fi payload malformed")
        return

    try:
        # wipe old Wi-Fi profiles
        for line in subprocess.check_output(
                ["nmcli", "-t", "-f", "UUID,TYPE", "connection", "show"],
                text=True).splitlines():
            uuid, ctype = line.split(':', 1)
            if ctype == "802-11-wireless":
                subprocess.run(["nmcli", "connection", "delete", uuid],
                               check=False, capture_output=True)

        # add new profile
        subprocess.run([
            "nmcli", "connection", "add",
            "type", "wifi", "ifname", "wlan0",
            "con-name", ssid, "ssid", ssid,
            "wifi-sec.key-mgmt", "wpa-psk",
            "wifi-sec.psk", pwd,
            "802-11-wireless-security.psk-flags", "0",
            "connection.autoconnect", "yes"
        ], check=True, capture_output=True, text=True)

        subprocess.run(["nmcli", "connection", "up", ssid],
                       check=True, capture_output=True, text=True)
        log_debug(f"Connected to “{ssid}”.")
    except subprocess.CalledProcessError as e:
        log_debug(f"nmcli error {e.returncode}: {e.stderr or e.stdout}")


def handle_orientation_change(arg: str):
    out = "HDMI-A-1"
    try:
        mode = subprocess.check_output(
            "wlr-randr | grep '(current)' | awk '{print $1\"@\"$3}'",
            shell=True, text=True).strip()
    except subprocess.CalledProcessError:
        log_debug("wlr-randr failed")
        return

    cfg = f"profile {{\n  output {out} enable mode {mode} position 0,0 transform {arg}\n}}\n"
    p = os.path.expanduser("~/.config/kanshi/config")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(cfg)
    subprocess.run(["killall", "kanshi"], check=False)
    subprocess.Popen(["kanshi", "-c", p],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log_debug("Portrait" if arg in ("90", "270") else "Landscape")


def ble_callback(value, options):
    if value is None:
        return
    msg = (bytes(value) if isinstance(value, list) else value).decode().strip()
    if msg.startswith("WIFI:"):
        handle_wifi_data(msg[5:].strip())
    elif msg.startswith("ORIENT:"):
        handle_orientation_change(msg[7:].strip())
    elif msg == "REBOOT":
        log_debug("Rebooting…")
        subprocess.run(["sudo", "reboot"])
    else:
        log_debug("Unknown BLE cmd")


# ───────────────────────── BLE server thread ───────────────────────
def start_gatt_server():
    while True:
        try:
            dongle = next(iter(adapter.Adapter.available()), None)
            if not dongle:
                log_debug("No BLE adapter!")
                time.sleep(5)
                continue

            periph = peripheral.Peripheral(dongle.address, local_name="PixelPaper")
            periph.add_service(1, PROVISIONING_SERVICE_UUID, primary=True)
            periph.add_characteristic(
                1, 1, PROVISIONING_CHAR_UUID,
                value=[], flags=['write', 'write-without-response'],
                write_callback=ble_callback)
            periph.add_characteristic(
                1, 2, SERIAL_CHAR_UUID,
                value=list(get_serial_number().encode()),
                flags=['read'],
                read_callback=lambda _opts: list(get_serial_number().encode()))
            periph.publish()
        except Exception as e:
            log_debug(f"BLE error: {e}")
        log_debug("Restarting BLE in 5 s…")
        time.sleep(5)


def start_gatt_thread(): threading.Thread(target=start_gatt_server, daemon=True).start()


# ───────────────────────── Wi-Fi / Chromium loop ────────────────────
def show_spinner(msg: str):
    label.configure(text=msg)
    spinner.start(10)           # 10 ms per step → smooth spin
    spinner.place(relx=.5, rely=.6, anchor="center")


def hide_spinner():
    spinner.stop()
    spinner.place_forget()
    # once Chromium is up, we can hide the Tk window entirely
    root.withdraw()


def poll_status():
    global chromium_process, fail_count, repo_updated

    if check_wifi_connection():
        if fail_count:
            fail_count = 0
        if not repo_updated:
            threading.Thread(target=launch.update_repo, daemon=True).start()
            repo_updated = True

        if chromium_process is None or chromium_process.poll() is not None:
            show_spinner("Wi-Fi OK – Loading frame…")
            try:
                subprocess.run(["pkill", "-f", "chromium"], check=False)
            except Exception:
                pass
            url = f"https://pixelpaper.com/frame.html?id={get_serial_number()}"
            chromium_process = subprocess.Popen(["chromium", "--kiosk", url])
            root.after(8000, hide_spinner)      # give Chromium ~8 s to appear
    else:
        fail_count += 1
        label.configure(text="No Wi-Fi – retrying…")
        spinner.stop()
        spinner.place_forget()

    root.after(3000, poll_status)               # re-poll every 3 s


# ───────────────────────────── Main UI ──────────────────────────────
root  = tb.Window(themename="litera")
style = root.style
style.colors.set('info', GREEN)
style.configure("TFrame", background="black")
style.configure("Status.TLabel", background="black", foreground=GREEN,
                font=("Helvetica", 48))

root.configure(bg="black")
root.title("Frame Status")
root.attributes('-fullscreen', True)
root.bind('<Escape>', lambda *_: root.attributes('-fullscreen', False))
root.bind("<<ToastHidden>>", lambda *_: root.attributes('-fullscreen', True))

label   = ttk.Label(root, text="Checking Wi-Fi…", style="Status.TLabel")
label.pack(expand=True)

spinner = ttk.Progressbar(root, mode="indeterminate", length=250,
                          bootstyle="info-striped-round")
# spinner is placed dynamically by show_spinner()

# fire everything up
start_gatt_thread()
poll_status()        # kicks off the periodic Wi-Fi check
root.mainloop()
