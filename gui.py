#!/usr/bin/env python3
"""
gui.py – Frame-side GUI & BLE provisioning for Pixel Paper
(plain-Tk widgets replaced with themed ttkbootstrap widgets)
"""
import os
import queue
import socket
import subprocess
import threading
import time
import tkinter as tk

from bluezero import adapter, peripheral
import ttkbootstrap as tb
from ttkbootstrap.toast import ToastNotification
from ttkbootstrap import ttk

import launch   # only used for get_serial_number() helper if you reinstate update_repo()

# ───────────────────────── Globals & constants ──────────────────────────
FAIL_MAX            = 3
chromium_process    = None
fail_count          = 0
provisioning_char   = None

PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"
SERIAL_CHAR_UUID          = "12345678-1234-5678-1234-56789abcdef2"

# ───────────────────────────── Toast queue ──────────────────────────────
toast_queue      = queue.SimpleQueue()
_toast_on_screen = False

def _show_next_toast():
    global _toast_on_screen
    if _toast_on_screen or toast_queue.empty():
        return

    _toast_on_screen = True
    message = toast_queue.get()

    class SmoothToast(ToastNotification):
        def hide_toast(self, *_):
            try:
                alpha = float(self.toplevel.attributes("-alpha"))
                if alpha <= 0.02:
                    self.toplevel.destroy(); _finish()
                else:
                    self.toplevel.attributes("-alpha", alpha - 0.02)
                    self.toplevel.after(25, self.hide_toast)
            except Exception:
                self.toplevel.destroy(); _finish()

    def _finish():
        global _toast_on_screen
        _toast_on_screen = False
        root.after_idle(_show_next_toast)

    SmoothToast(title="Pixel Paper",
                message=message,
                bootstyle="info",
                duration=3000,
                position=(10, 10, "ne"),
                alpha=0.95).show_toast()

def log_debug(msg: str):
    toast_queue.put(msg)
    try:
        root.after_idle(_show_next_toast)
    except NameError:
        pass
    print(msg)

# ───────────────────────────── Utilities ────────────────────────────────
def get_serial_number() -> str:
    try:
        with open('/proc/device-tree/serial-number') as f:
            return "PX" + f.read().strip('\x00\n ')
    except Exception:
        return "PXunknown"

def disable_pairing():
    try:
        subprocess.run(["bluetoothctl"], input="pairable no\nquit\n",
                       text=True, capture_output=True, check=True)
    except Exception as e:
        log_debug(f"Failed to disable pairing: {e}")

def check_wifi_connection(retries=2) -> bool:
    for _ in range(retries):
        try:
            s = socket.create_connection(("8.8.8.8", 53), timeout=3)
            s.close(); return True
        except OSError:
            time.sleep(0.3)
    return False

# ───────────────────────── Wi-Fi & Chromium ─────────────────────────────
def update_status():
    global chromium_process, fail_count
    try:
        if check_wifi_connection():
            fail_count = 0
            if chromium_process is None or chromium_process.poll() is not None:
                label.configure(text="Wi-Fi Connected")
                subprocess.run(["pkill", "-f", "chromium"], check=False)
                url = f"https://pixelpaper.com/frame.html?id={get_serial_number()}"
                chromium_process = subprocess.Popen(["chromium", "--kiosk", url])
        else:
            fail_count += 1
            if fail_count > FAIL_MAX:
                label.configure(text="Waiting for Wi-Fi…")
    except Exception as e:
        log_debug(f"update_status: {e}")

# ───────────────────────── BLE helper callbacks ────────────────────────
def handle_wifi_data(data: str):
    """Parse 'SSID;PASS:pwd' payload and create a Wi-Fi profile."""
    try:
        ssid, pass_part = data.split(';', 1)
        password = pass_part.split(':', 1)[1]
    except ValueError:
        log_debug("Wi-Fi payload malformed; expected SSID;PASS:pwd")
        return

    try:
        profiles = subprocess.check_output(
            ["nmcli", "-t", "-f", "UUID,TYPE", "connection", "show"],
            text=True).splitlines()

        for line in profiles:
            uuid, ctype = line.split(':', 1)
            if ctype == "802-11-wireless":
                subprocess.run(["nmcli", "connection", "delete", uuid],
                               check=False, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        log_debug(f"Could not list profiles: {e.stderr.strip()}")

    try:
        subprocess.run([
            "nmcli", "connection", "add", "type", "wifi", "ifname", "wlan0",
            "con-name", ssid, "ssid", ssid,
            "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password,
            "802-11-wireless-security.psk-flags", "0",
            "connection.autoconnect", "yes"], check=True)

        subprocess.run(["nmcli", "connection", "reload"], check=True)
        subprocess.run(["nmcli", "connection", "up", ssid], check=True)

        log_debug(f"Connected to: '{ssid}'")
    except subprocess.CalledProcessError as e:
        log_debug(f"nmcli error {e.returncode}: {e.stderr.strip() or e.stdout.strip()}")

def handle_orientation_change(data: str):
    """Rotate HDMI-A-1 output via kanshi."""
    output = "HDMI-A-1"
    try:
        mode = subprocess.check_output(
            "wlr-randr | grep '(current)' | awk '{print $1\"@\"$3}'",
            shell=True, text=True).strip()
    except subprocess.CalledProcessError as e:
        log_debug(f"Failed to detect current mode: {e}")
        return

    cfg = f"profile {{\n    output {output} enable mode {mode} position 0,0 transform {data}\n}}\n"
    cfg_path = os.path.expanduser("~/.config/kanshi/config")
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    with open(cfg_path, "w") as f: f.write(cfg)
    os.chmod(cfg_path, 0o600)

    subprocess.run(["killall", "kanshi"], check=False)
    subprocess.Popen(["kanshi", "-c", cfg_path],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log_debug("Portrait" if data in ("90", "270") else "Landscape")

def ble_callback(value, _options):
    try:
        if value is None: return
        value_bytes = bytes(value) if isinstance(value, list) else value
        message = value_bytes.decode("utf-8", errors="ignore").strip()

        if message.startswith("WIFI:"):
            handle_wifi_data(message[5:].strip())
        elif message.startswith("ORIENT:"):
            handle_orientation_change(message[7:].strip())
        elif message == "REBOOT":
            log_debug("Restarting…"); subprocess.run(["sudo", "reboot"], check=False)
        else:
            log_debug("Unknown BLE command")
    except Exception as e:
        log_debug(f"ble_callback: {e}")

# ───────────────────────── BLE server thread ────────────────────────────
def start_gatt_server():
    global provisioning_char
    while True:
        try:
            dongles = adapter.Adapter.available()
            if not dongles:
                log_debug("No Bluetooth adapters available!")
                time.sleep(5); continue

            addr = list(dongles)[0].address
            ble = peripheral.Peripheral(addr, local_name="PixelPaper")
            ble.add_service(1, PROVISIONING_SERVICE_UUID, primary=True)
            provisioning_char = ble.add_characteristic(
                1, 1, PROVISIONING_CHAR_UUID,
                value=[], notifying=False,
                flags=['write', 'write-without-response'],
                write_callback=ble_callback)
            ble.add_characteristic(
                1, 2, SERIAL_CHAR_UUID,
                value=list(get_serial_number().encode()),
                notifying=False, flags=['read'],
                read_callback=lambda _opt: list(get_serial_number().encode()))
            ble.publish()
        except Exception as e:
            log_debug(f"GATT error: {e}")
        time.sleep(5)

def start_gatt_server_thread():
    threading.Thread(target=start_gatt_server, daemon=True).start()

# ──────────────────────────── Main GUI ─────────────────────────────────
if __name__ == "__main__":
    GREEN = "#1FC742"

    root = tb.Window(themename="litera")
    root.style.colors.set("info", GREEN)
    root.style.configure("TFrame", background="black")           # full bg
    root.style.configure("Status.TLabel",
                         background="black", foreground=GREEN,
                         font=("Helvetica", 48))

    root.configure(bg="black")
    root.title("Frame Status")
    root.attributes("-fullscreen", True)
    root.bind("<Escape>", lambda e: root.attributes("-fullscreen", False))

    label = ttk.Label(root, text="Checking Wi-Fi…", style="Status.TLabel")
    label.pack(expand=True)

    disable_pairing()
    start_gatt_server_thread()
    update_status()

    root.mainloop()
