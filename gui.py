#!/usr/bin/env python3
"""
PixelPaper frame launcher + BLE provisioning ‑‑ GUI + GATT server
===============================================================

Changes in this version
-----------------------
• handle_wifi_data() is now *idempotent*:
  – If wlan0 is already connected to the target SSID **and** the stored PSK
    matches the one just received, it exits early, so NetworkManager never
    asks for authentication and no LXPolkit pop‑up appears.
  – Otherwise it deletes/creates the profile and brings it up as before.
"""

import tkinter as tk
import socket
import subprocess
import time
import threading
import os
from bluezero import adapter, peripheral

# ─── BLE UUIDs ────────────────────────────────────────────
PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"
SERIAL_CHAR_UUID          = "12345678-1234-5678-1234-56789abcdef2"

# ─── globals ──────────────────────────────────────────────
debug_messages = []
chromium_cmd   = ["chromium", "--kiosk", "https://pixelpaper.com/frame.html"]
chromium_proc  = None

# ─── helpers ──────────────────────────────────────────────
def get_serial_number():
    try:
        with open('/proc/device-tree/serial-number', 'r') as f:
            return "PX" + f.read().strip('\x00\n ')
    except Exception:
        return "PXunknown"

def log_debug(msg: str):
    debug_messages.append(msg)
    debug_text.config(state=tk.NORMAL)
    debug_text.delete(1.0, tk.END)
    debug_text.insert(tk.END, "\n".join(debug_messages[-10:]))
    debug_text.config(state=tk.DISABLED)
    print(msg)

def disable_pairing():
    try:
        subprocess.run(
            ["bluetoothctl"], input="pairable no\nquit\n",
            text=True, capture_output=True, check=True
        )
    except Exception as e:
        log_debug(f"Failed to disable pairing: {e}")

def check_wifi_connection():
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=2)
        return True
    except OSError:
        return False

# ─── Wi‑Fi provisioner (Option 1) ─────────────────────────
def handle_wifi_data(payload: str):
    """
    BLE payload: 'MySSID;PASS:supersecret'
    • If wlan0 is already connected to that SSID *and* the stored PSK
      equals the new one, do nothing → no GUI prompt.
    • Otherwise delete/create the profile and bring it up.
    """
    log_debug(f"Handling Wi‑Fi data: {payload}")

    # 1. parse
    if ';PASS:' not in payload:
        log_debug("✗ Invalid payload (need SSID;PASS:psk)")
        return
    ssid, password = payload.split(';PASS:', 1)
    ssid, password = ssid.strip(), password.strip()

    if not ssid or not password:
        log_debug("✗ Missing SSID or password")
        return

    try:
        # 2. early exit if already on SSID with same PSK
        active = subprocess.check_output(
            ["nmcli", "-t", "-f", "NAME,DEVICE,ACTIVE", "connection", "show", "--active"],
            text=True
        )
        for line in active.splitlines():
            name, dev, active_flag = line.split(":")
            if dev == "wlan0" and active_flag == "yes" and name == ssid:
                current_psk = subprocess.check_output(
                    ["nmcli", "--show-secrets", "-g",
                     "802-11-wireless-security.psk", "connection", "show", ssid],
                    text=True
                ).strip()
                if current_psk == password:
                    log_debug(f"✓ Already on '{ssid}' with correct PSK – skipping update")
                    return
                else:
                    log_debug("PSK changed – will update profile")
                break

        # 3. (re)create profile
        subprocess.run(["nmcli", "connection", "delete", ssid],
                       check=False, capture_output=True, text=True)

        subprocess.run([
            "nmcli", "connection", "add",
            "type", "wifi",
            "ifname", "wlan0",
            "con-name", ssid,
            "ssid", ssid,
            "wifi-sec.key-mgmt", "wpa-psk",
            "wifi-sec.psk", password,
            "connection.autoconnect", "yes"
        ], check=True)

        # 4. bring it up
        subprocess.run(["nmcli", "connection", "up", ssid], check=True)
        log_debug(f"✓ Connected to '{ssid}' (non‑interactive)")

    except subprocess.CalledProcessError as e:
        err = e.stderr.strip() or e.stdout.strip()
        log_debug(f"nmcli error ({e.returncode}): {err}")
    except Exception as e:
        log_debug(f"Unhandled Wi‑Fi error: {e}")

# ─── orientation helper (unchanged) ───────────────────────
def handle_orientation_change(data: str):
    output = "HDMI-A-1"
    try:
        mode = subprocess.check_output(
            "wlr-randr | grep '(current)' | awk '{print $1\"@\"$3}'",
            shell=True, text=True
        ).strip()
    except subprocess.CalledProcessError as e:
        log_debug(f"Failed to detect current mode: {e}")
        return

    cfg = f"""profile {{
    output {output} enable mode {mode} position 0,0 transform {data}
}}"""
    cfg_path = os.path.expanduser("~/.config/kanshi/config")
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    with open(cfg_path, "w") as f:
        f.write(cfg)
    os.chmod(cfg_path, 0o600)

    subprocess.run(["killall", "kanshi"], check=False)
    subprocess.Popen(["kanshi", "-c", cfg_path],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log_debug(f"Rotated {output} → {data}°")

# ─── BLE callback ─────────────────────────────────────────
def ble_callback(value, options):
    try:
        msg = bytes(value).decode()
        if msg.startswith("WIFI:"):
            handle_wifi_data(msg[len("WIFI:"):])
        elif msg.startswith("ORIENT:"):
            handle_orientation_change(msg[len("ORIENT:"):].strip())
    except Exception as e:
        log_debug(f"BLE callback error: {e}")

# ─── GATT server thread ───────────────────────────────────
def start_gatt_server():
    while True:
        try:
            dongle = next(iter(adapter.Adapter.available()))
            periph = peripheral.Peripheral(dongle.address, local_name="PixelPaper")

            periph.add_service(srv_id=1, uuid=PROVISIONING_SERVICE_UUID, primary=True)
            periph.add_characteristic(
                1, 1, PROVISIONING_CHAR_UUID, [], False,
                ['write', 'write-without-response'],
                write_callback=ble_callback
            )
            periph.add_characteristic(
                1, 2, SERIAL_CHAR_UUID,
                list(get_serial_number().encode()), False, ['read']
            )
            periph.publish()
        except Exception as e:
            log_debug(f"GATT error: {e}")
        time.sleep(5)

# ─── GUI + Chromium monitor ───────────────────────────────
def update_status():
    global chromium_proc
    try:
        up = check_wifi_connection()
        label.config(text="Wi‑Fi Connected" if up else "Waiting for Wi‑Fi")
        if up:
            if chromium_proc is None or chromium_proc.poll() is not None:
                subprocess.run(["pkill", "-f", "chromium"], check=False)
                chromium_proc = subprocess.Popen(chromium_cmd)
        else:
            if chromium_proc and chromium_proc.poll() is None:
                subprocess.run(["pkill", "-f", "chromium"], check=False)
                chromium_proc = None
    except Exception as e:
        log_debug(f"update_status error: {e}")
    finally:
        root.after(5000, update_status)

# ─── main ─────────────────────────────────────────────────
if __name__ == '__main__':
    root = tk.Tk()
    root.title("Frame Status")
    root.attributes('-fullscreen', False)

    label = tk.Label(root, text="Checking Wi‑Fi...", font=("Helvetica", 48))
    label.pack(expand=True)

    debug_text = tk.Text(root, height=10, bg="#f0f0f0")
    debug_text.pack(fill=tk.X, side=tk.BOTTOM)
    debug_text.config(state=tk.DISABLED)

    disable_pairing()
    threading.Thread(target=start_gatt_server, daemon=True).start()
    update_status()
    root.mainloop()
