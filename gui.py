#!/usr/bin/env python3
import tkinter as tk
import socket
import subprocess
import time
import threading
import os
from bluezero import adapter, peripheral

# Global GUI variables and flags.
launched = False
debug_messages = []
provisioning_char = None

# UUIDs for custom provisioning service and characteristics.
PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"
SERIAL_CHAR_UUID          = "12345678-1234-5678-1234-56789abcdef2"

# Chromium command and process
chromium_cmd = ["chromium", "--kiosk", "https://pixelpaper.com/frame.html"]
chromium_process = None

def get_serial_number():
    try:
        with open('/proc/device-tree/serial-number', 'r') as f:
            serial = f.read().strip('\x00\n ')
        return "PX" + serial
    except Exception as e:
        return "PXunknown"

def log_debug(message):
    global debug_text
    debug_messages.append(message)
    # Limit log length to the last 10 messages.
    debug_text.config(state=tk.NORMAL)
    debug_text.delete(1.0, tk.END)
    debug_text.insert(tk.END, "\n".join(debug_messages[-10:]))
    debug_text.config(state=tk.DISABLED)
    print(message)

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

def check_wifi_connection():
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=2)
        return True
    except OSError:
        return False

def update_status():
    global chromium_process
    try:
        up = check_wifi_connection()
        if up:
            label.config(text="WiFi Connected. Launching frame…")
            if chromium_process is None or chromium_process.poll() is not None:
                subprocess.run(["pkill", "-f", "chromium"], check=False)
                chromium_process = subprocess.Popen(chromium_cmd)
        else:
            label.config(text="WiFi Not Connected. Waiting…")
            if chromium_process and chromium_process.poll() is None:
                subprocess.run(["pkill", "-f", "chromium"], check=False)
                chromium_process = None
    except Exception as e:
        log_debug("Error in update_status: " + str(e))
    finally:
        root.after(5000, update_status)

# ─────────────────────────────────────────────────────────────
# Updated Wi‑Fi handler  (Option 1: skip if already connected)
# ─────────────────────────────────────────────────────────────
def handle_wifi_data(data: str):
    """
    BLE payload format:  "MySSID;PASS:supersecret"
    ‑ If wlan0 is already up on that SSID *and* the stored PSK matches,
      do nothing (avoids NetworkManager secrets‑agent pop‑up).
    ‑ Otherwise recreate / update the profile non‑interactively.
    """
    log_debug("Handling WiFi data: " + data)

    # 1. Parse
    parts = data.split(';')
    ssid = parts[0].strip()
    password = next((p.split(':', 1)[1] for p in parts[1:] if p.upper().startswith("PASS:")), None)
    if not ssid or password is None:
        log_debug("Invalid format, expected SSID;PASS:password")
        return

    try:
        # 2. Early‑exit if already connected with same PSK
        #    (requires --show-secrets and root privileges)
        active = subprocess.check_output(
            ["nmcli", "-t", "-f", "NAME,DEVICE,ACTIVE", "connection", "show", "--active"],
            text=True
        )
        already_up = False
        for line in active.splitlines():
            name, dev, active_flag = line.split(":")
            if dev == "wlan0" and active_flag == "yes" and name == ssid:
                stored_psk = subprocess.check_output(
                    ["nmcli", "--show-secrets", "-s", "-g", "802-11-wireless-security.psk",
                     "connection", "show", ssid],
                    text=True
                ).strip()
                if stored_psk == password:
                    already_up = True
                break

        if already_up:
            log_debug(f"Already on '{ssid}' with correct PSK → skip")
            return

        # 3. Delete old profile (if any) so we start fresh
        subprocess.run(["nmcli", "connection", "delete", ssid],
                       check=False, capture_output=True, text=True)

        # 4. Add / modify profile silently
        subprocess.run([
            "nmcli", "connection", "add",
            "type", "wifi",
            "ifname", "wlan0",
            "con-name", ssid,
            "ssid", ssid,
            "wifi-sec.key-mgmt", "wpa-psk",
            "wifi-sec.psk", password,
            "connection.autoconnect", "yes"
        ], check=True, capture_output=True, text=True)
        log_debug(f"Configured profile for '{ssid}'")

        # 5. Bring it up (non‑interactive; PSK already stored)
        subprocess.run(["nmcli", "connection", "up", ssid],
                       check=True, capture_output=True, text=True)
        log_debug(f"Connection up on '{ssid}'")

    except subprocess.CalledProcessError as e:
        err = e.stderr.strip() or e.stdout.strip()
        log_debug(f"nmcli error ({e.returncode}): {err}")
    except Exception as e:
        log_debug("Failed to configure WiFi: " + str(e))

# ─────────────────────────────────────────────────────────────
#      Orientation handler & BLE infrastructure (unchanged)
# ─────────────────────────────────────────────────────────────
def handle_orientation_change(data):
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
    log_debug(f"Rotated {output} → {data}° via kanshi")

def ble_callback(value, options):
    try:
        message = bytes(value).decode('utf-8')
        if message.startswith("WIFI:"):
            handle_wifi_data(message[len("WIFI:"):])
        elif message.startswith("ORIENT:"):
            handle_orientation_change(message[len("ORIENT:"):])
    except Exception as e:
        log_debug("Error in BLE callback: " + str(e))

def start_gatt_server():
    global provisioning_char
    while True:
        try:
            dongles = adapter.Adapter.available()
            if not dongles:
                log_debug("No Bluetooth adapters available.")
                time.sleep(5)
                continue
            addr = list(dongles)[0].address
            ble_periph = peripheral.Peripheral(addr, local_name="PixelPaper")
            ble_periph.add_service(1, PROVISIONING_SERVICE_UUID, True)
            provisioning_char = ble_periph.add_characteristic(
                1, 1, PROVISIONING_CHAR_UUID, [], False,
                ['write', 'write-without-response'], ble_callback, None, None
            )
            ble_periph.add_characteristic(
                1, 2, SERIAL_CHAR_UUID,
                list(get_serial_number().encode()), False,
                ['read'],
                read_callback=lambda opt: list(get_serial_number().encode())
            )
            log_debug("Publishing GATT server...")
            ble_periph.publish()
        except Exception as e:
            log_debug("GATT server error: " + str(e))
        time.sleep(5)

def start_gatt_server_thread():
    threading.Thread(target=start_gatt_server, daemon=True).start()

# ---------------- Main GUI ----------------
if __name__ == '__main__':
    root = tk.Tk()
    root.title("Frame Status")
    root.attributes('-fullscreen', False)

    label = tk.Label(root, text="Checking WiFi...", font=("Helvetica", 48))
    label.pack(expand=True)

    debug_text = tk.Text(root, height=10, bg="#f0f0f0")
    debug_text.pack(fill=tk.X, side=tk.BOTTOM)
    debug_text.config(state=tk.DISABLED)

    disable_pairing()
    start_gatt_server_thread()
    update_status()

    root.mainloop()
