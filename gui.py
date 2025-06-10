#!/usr/bin/env python3
"""
Pixel Paper – Full-screen status / provisioning GUI
───────────────────────────────────────────────────
• Runs between launch.py and Chromium on a headless frame
• Portrait or landscape, auto-scaling fonts
• Brand palette 010101 / 1FC742 / 025B18 / 161616
• Toast messages (upper-right) replace the old debug panel
• All original Wi-Fi-provisioning, BLE, kanshi-rotation and
  repository-update logic kept intact
"""
from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from typing import List, Optional

from bluezero import adapter, peripheral
import launch  # for update_repo()

# ──────────────────────────────────────────────────────────────────────────
#  Brand colours
# ──────────────────────────────────────────────────────────────────────────
CLR_BG      = "#010101"   # background
CLR_ACCENT  = "#1FC742"   # bright green
CLR_ACCENT2 = "#025B18"   # darker accent (toast background)
CLR_TEXT    = "#E8E8E8"   # light grey text

# ──────────────────────────────────────────────────────────────────────────
#  BLE UUIDs (unchanged)
# ──────────────────────────────────────────────────────────────────────────
PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"
SERIAL_CHAR_UUID          = "12345678-1234-5678-1234-56789abcdef2"

# ──────────────────────────────────────────────────────────────────────────
#  Toast-style logging
# ──────────────────────────────────────────────────────────────────────────
toast_stack: List["Toast"] = []

def _fade_hex(hex_color: str, factor: float) -> str:
    """Multiply a hex colour by 0‥1 alpha factor (simple RGB scaling)."""
    r = int(int(hex_color[1:3], 16) * factor)
    g = int(int(hex_color[3:5], 16) * factor)
    b = int(int(hex_color[5:7], 16) * factor)
    return f"#{r:02x}{g:02x}{b:02x}"

class Toast:
    """Ephemeral notification that slides in, stacks, then auto-fades."""
    WIDTH      = 380
    PAD        = 12
    SLIDE_MS   = 250      # slide-in duration
    ALIVE_MS   = 4_000    # time fully visible
    FADE_MS    = 400      # fade-out duration

    def __init__(self, master: tk.Tk, message: str):
        self.master = master
        self.frame  = tk.Frame(master, bg=CLR_ACCENT2, highlightthickness=0, bd=0)
        self.label  = tk.Label(
            self.frame,
            text=message,
            fg=CLR_TEXT,
            bg=CLR_ACCENT2,
            justify="left",
            wraplength=self.WIDTH - 2 * self.PAD
        )
        self.label.pack(padx=self.PAD, pady=(self.PAD, self.PAD - 2), anchor="w")

        # determine initial vertical stack position
        self.frame.update_idletasks()
        self.height = self.frame.winfo_height()
        y = 20
        for t in toast_stack:
            y += t.height + 10

        # place off-screen to the right first
        self.frame.place(relx=1.0, x=self.WIDTH + 20, y=y, anchor="ne")
        toast_stack.append(self)

        self._slide_in()
        self.master.after(self.ALIVE_MS, self._fade_and_destroy)

    # ─────────────────────────────── helpers ─────────────────────────────
    def _slide_in(self):
        steps = max(1, int(self.SLIDE_MS / 16))  # ~60 FPS
        dx    = (self.WIDTH + 20) / steps

        def step(i=0):
            if i >= steps:
                self.frame.place_configure(x=0)
                return
            self.frame.place_configure(x=-(dx * i))
            self.master.after(16, step, i + 1)

        step()

    def _fade_and_destroy(self):
        steps = max(1, int(self.FADE_MS / 50))
        def fade(opacity):
            if opacity <= 0:
                self.frame.destroy()
                toast_stack.remove(self)
                _reflow_toasts()
                return
            new_bg = _fade_hex(CLR_ACCENT2, opacity)
            new_fg = _fade_hex(CLR_TEXT,   opacity)
            self.frame.configure(bg=new_bg)
            self.label.configure(bg=new_bg, fg=new_fg)
            self.master.after(50, fade, opacity - (1 / steps))
        fade(1.0)

def _reflow_toasts():
    """Recalculate y-positions after a toast disappears."""
    y = 20
    for t in toast_stack:
        t.frame.place_configure(y=y)
        y += t.height + 10

def log_debug(msg: str):
    print(msg)                   # still goes to stdout / journald
    root.after(0, Toast, root, msg)

# ──────────────────────────────────────────────────────────────────────────
#  Utility helpers copied from original gui.py
# ──────────────────────────────────────────────────────────────────────────
def get_serial_number() -> str:
    try:
        with open('/proc/device-tree/serial-number', 'r') as f:
            serial = f.read().strip('\x00\n ')
        return "PX" + serial
    except Exception:
        return "PXunknown"

def check_wifi_connection(retries: int = 2) -> bool:
    for _ in range(retries):
        try:
            sock = socket.create_connection(("8.8.8.8", 53), timeout=2)
            sock.close()
            return True
        except OSError:
            time.sleep(0.25)
    return False

def nm_reconnect():
    try:
        ssid = subprocess.check_output(
            ["nmcli", "-t", "-f", "NAME,TYPE,DEVICE,ACTIVE", "connection", "show", "--active"],
            text=True
        ).split(':')[0]
        subprocess.run(["nmcli", "connection", "up", ssid], check=False)
        log_debug(f"nmcli reconnect issued for {ssid}")
    except Exception as e:
        log_debug(f"nm_reconnect err: {e}")

# ──────────────────────────────────────────────────────────────────────────
#  Network / Chromium watchdog
# ──────────────────────────────────────────────────────────────────────────
chromium_proc: Optional[subprocess.Popen] = None
repo_updated  = False
fail_count    = 0
FAIL_MAX      = 3

def update_status():
    """Periodic check for connectivity and chromium process."""
    global chromium_proc, repo_updated, fail_count

    online = check_wifi_connection()

    if online:
        status_lbl.config(text="Connected ✓", fg=CLR_ACCENT)
        if fail_count:
            fail_count = 0

        if not repo_updated:
            threading.Thread(target=launch.update_repo, daemon=True).start()
            repo_updated = True

        if chromium_proc is None or chromium_proc.poll() is not None:
            url = f"https://pixelpaper.com/frame.html?id={get_serial_number()}"
            subprocess.run(["pkill", "-f", "chromium"], check=False)
            chromium_proc = subprocess.Popen(["chromium", "--kiosk", url])
            log_debug("Chromium launched for frame display.")
    else:
        if fail_count < FAIL_MAX:
            fail_count += 1
            status_lbl.config(text="Waiting for Wi-Fi…", fg=CLR_TEXT)
        else:
            status_lbl.config(text="Offline ⚠", fg="#ff9933")
            nm_reconnect()

    root.after(3_000, update_status)

# ──────────────────────────────────────────────────────────────────────────
#  Bluetooth LE provisioning (original logic, only log_debug changed)
# ──────────────────────────────────────────────────────────────────────────
def handle_wifi_data(data: str):
    """
    Expect data "MySSID;PASS:secret" then
    (1) wipe existing Wi-Fi profiles,
    (2) add stored-PSK profile,
    (3) connect.
    """
    log_debug("Handling Wi-Fi data: " + data)

    # 1. parse
    try:
        ssid, pass_part = data.split(';', 1)
        password = pass_part.split(':', 1)[1]
    except ValueError:
        log_debug("Wi-Fi payload malformed; expected SSID;PASS:pwd")
        return

    # 2. delete all existing Wi-Fi profiles
    try:
        profiles = subprocess.check_output(
            ["nmcli", "-t", "-f", "UUID,TYPE", "connection", "show"],
            text=True
        ).splitlines()
        for line in profiles:
            uuid, ctype = line.split(':', 1)
            if ctype == "802-11-wireless":
                subprocess.run(
                    ["nmcli", "connection", "delete", uuid],
                    check=False, capture_output=True, text=True
                )
    except subprocess.CalledProcessError as e:
        log_debug(f"Could not list profiles: {e.stderr.strip()}")

    # 3. add new profile
    try:
        subprocess.run([
            "nmcli", "connection", "add",
            "type", "wifi",
            "ifname", "wlan0",
            "con-name", ssid,
            "ssid", ssid,
            "wifi-sec.key-mgmt", "wpa-psk",
            "wifi-sec.psk", password,
            "802-11-wireless-security.psk-flags", "0",
            "connection.autoconnect", "yes"
        ], check=True, capture_output=True, text=True)

        subprocess.run(["nmcli", "connection", "reload"], check=True)
        subprocess.run(["nmcli", "connection", "up", ssid], check=True,
                       capture_output=True, text=True)

        log_debug(f"Activated Wi-Fi connection '{ssid}'.")
    except subprocess.CalledProcessError as e:
        log_debug(f"nmcli error {e.returncode}: {e.stderr.strip() or e.stdout.strip()}")

def handle_orientation_change(data: str):
    """
    Rotate the display via kanshi + wlr-randr.
    data: "normal", "90", "180", "270"
    """
    output = "HDMI-A-1"  # Adjust if your output name differs

    # 1. fetch current mode@freq
    try:
        mode = subprocess.check_output(
            "wlr-randr | grep '(current)' | awk '{print $1\"@\"$3}'",
            shell=True, text=True
        ).strip()
    except subprocess.CalledProcessError as e:
        log_debug(f"Failed to detect current mode: {e}")
        return

    # 2. write kanshi config
    cfg = (f"profile {{\n"
           f"    output {output} enable mode {mode} position 0,0 transform {data}\n"
           f"}}\n")
    cfg_path = os.path.expanduser("~/.config/kanshi/config")
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    with open(cfg_path, "w") as f:
        f.write(cfg)
    os.chmod(cfg_path, 0o600)
    log_debug(f"Wrote kanshi config: mode={mode}, transform={data}")

    # 3. restart kanshi
    subprocess.run(["killall", "kanshi"], check=False)
    subprocess.Popen(
        ["kanshi", "-c", cfg_path],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    log_debug(f"Rotated display → {data}°")

def ble_callback(value, options):
    try:
        if value is None:
            return
        value_bytes = (
            bytes(value) if isinstance(value, list)
            else bytes(value) if isinstance(value, (bytes, bytearray))
            else None
        )
        if value_bytes is None:
            log_debug(f"Unexpected BLE value type: {type(value)}")
            return

        message = value_bytes.decode("utf-8", errors="ignore").strip()
        log_debug("Received BLE data: " + message)

        if message.startswith("WIFI:"):
            handle_wifi_data(message[len("WIFI:"):].strip())
        elif message.startswith("ORIENT:"):
            handle_orientation_change(message[len("ORIENT:"):].strip())
        elif message == "REBOOT":
            log_debug("Reboot command received; rebooting.")
            subprocess.run(["sudo", "reboot"], check=False)
        else:
            log_debug("Unknown BLE command.")
    except Exception as e:
        log_debug("Error in ble_callback: " + str(e))

def start_gatt_server():
    """Blocking loop that (re)publishes the provisioning GATT service."""
    while True:
        try:
            dongles = adapter.Adapter.available()
            if not dongles:
                log_debug("No Bluetooth adapters available.")
                time.sleep(4)
                continue

            dongle_addr = list(dongles)[0].address
            ble_periph = peripheral.Peripheral(dongle_addr, local_name="PixelPaper")
            ble_periph.add_service(1, PROVISIONING_SERVICE_UUID, primary=True)

            ble_periph.add_characteristic(
                1, 1, PROVISIONING_CHAR_UUID,
                value=[], notifying=False,
                flags=['write', 'write-without-response'],
                write_callback=ble_callback
            )
            ble_periph.add_characteristic(
                1, 2, SERIAL_CHAR_UUID,
                value=list(get_serial_number().encode()),
                notifying=False, flags=['read'],
                read_callback=lambda _: list(get_serial_number().encode())
            )
            log_debug("Publishing GATT provisioning service…")
            ble_periph.publish()
            log_debug("GATT event loop ended.")
        except Exception as e:
            log_debug(f"GATT server error: {e}")
        log_debug("Restarting GATT server in 5 s…")
        time.sleep(5)

def start_gatt_thread():
    threading.Thread(target=start_gatt_server, daemon=True).start()

def disable_pairing():
    try:
        subprocess.run(
            ["bluetoothctl"],
            input="pairable no\nquit\n",
            text=True,
            capture_output=True,
            check=True
        )
    except Exception as e:
        log_debug("Failed to disable pairing: " + str(e))

# ──────────────────────────────────────────────────────────────────────────
#  Tkinter full-screen UI
# ──────────────────────────────────────────────────────────────────────────
root = tk.Tk()
root.title("Pixel Paper – Setup")
root.configure(bg=CLR_BG)
root.attributes('-fullscreen', True)
root.bind("<Escape>", lambda e: None)  # ignore Esc (no keyboard)

status_font = tkfont.Font(family="Helvetica", size=64, weight="bold")
status_lbl  = tk.Label(root, text="Checking Wi-Fi…",
                       fg=CLR_TEXT, bg=CLR_BG,
                       font=status_font)
status_lbl.pack(expand=True)

def _autoscale(event=None):
    size = max(root.winfo_width(), root.winfo_height()) // 18
    status_font.configure(size=size)
root.bind("<Configure>", _autoscale)

# ──────────────────────────────────────────────────────────────────────────
#  Kick it all off
# ──────────────────────────────────────────────────────────────────────────
disable_pairing()
start_gatt_thread()
root.after(200, update_status)   # slight delay before first check
root.mainloop()
