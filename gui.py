#!/usr/bin/env python3
import os, time, threading, subprocess, socket
import tkinter as tk
from functools import partial
from bluezero import adapter, peripheral

# Import update_repo so we can refresh once Wi‑Fi is up
import launch                                 # our sibling launcher script

# ── NEW: modern themed widgets & toast notifications ──────────────────────────
try:
    import ttkbootstrap as ttk
    from ttkbootstrap.toast import ToastNotification
except ImportError:
    raise SystemExit(
        "This version of gui.py needs ttkbootstrap. `$ pip install ttkbootstrap`"
    )

# ── Brand colours ───────────────────────────────────────────────────────────
BG = "#121212"
FG = "#e0e0e0"
PRIMARY = "#007bff"
SUCCESS = "#28a745"
WARNING = "#ffc107"
DANGER = "#dc3545"
INFO = "#17a2b8"
LIGHT = "#f8f9fa"
DARK = "#343a40"

# Global GUI variables and flags.
launched = False
debug_messages = []
provisioning_char = None
repo_updated = False          # ← new: run update only once

# UUIDs for custom provisioning service and characteristics.
PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"
SERIAL_CHAR_UUID          = "12345678-1234-5678-1234-56789abcdef2"

FAIL_MAX   = 3          # how many misses before we declare “offline”
fail_count = 0

# Chromium command and process
chromium_process = None

def get_serial_number():
    try:
        with open('/proc/device-tree/serial-number', 'r') as f:
            serial = f.read().strip('\x00\n ')
        return "PX" + serial
    except Exception:
        return "PXunknown"

def log_debug(message: str):
    """Show a toast instead of writing into the old Text widget."""
    global toast_mgr
    debug_messages.append(message)
    toast_mgr.show(message)
    print(message)          # still log to stdout for journalctl

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

def check_wifi_connection(retries: int = 2) -> bool:
    for _ in range(retries):
        try:
            s = socket.create_connection(("8.8.8.8", 53), timeout=3)
            s.close()
            return True
        except OSError:
            time.sleep(0.3)
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

def update_status():
    global chromium_process, fail_count, repo_updated
    try:
        up = check_wifi_connection()
        if up:
            # was offline → now online
            if fail_count:
                fail_count = 0
                if not repo_updated:
                    threading.Thread(
                        target=launch.update_repo,
                        daemon=True
                    ).start()
                    repo_updated = True

            # (re)start Chromium if it’s not running
            if chromium_process is None or chromium_process.poll() is not None:
                status_lbl.configure(text="Wi-Fi OK\nStarting frame…", bootstyle="success")
                subprocess.run(["pkill", "-f", "chromium"], check=False)
                url = f"https://pixelpaper.com/frame.html?id={get_serial_number()}"
                # url = f"https://pixelpaper.com/daily_prophet.html"
                # url =f"https://pixelpaper.com/test.html"
                chromium_process = subprocess.Popen(
                    ["chromium", "--kiosk", url]
                )

        else:
            status_lbl.configure(
                text=f"Waiting for Wi-Fi ({fail_count}/{FAIL_MAX})",
                bootstyle="warning",
            )
            log_debug("Wi-Fi down, waiting to retry")

    except Exception as e:
        log_debug(f"update_status error: {e}")

def handle_wifi_data(data: str):
    """
    Expect data in the form  "MySSID;PASS:supersecret"
    and (re)create a *single* NetworkManager keyfile profile
    that already stores the PSK, so NM never needs to ask.
    """
    log_debug("Handling WiFi data: " + data)

    # ---- 1. parse ---------------------------------------------------------
    try:
        ssid, pass_part = data.split(';', 1)
        password = pass_part.split(':', 1)[1]
    except ValueError:
        log_debug("WiFi payload malformed; expected SSID;PASS:pwd")
        return

    # ---- 2. wipe every Wi‑Fi profile (safer than one‑by‑one) -------------
    try:
        profiles = subprocess.check_output(
            ["nmcli", "-t", "-f", "UUID,TYPE", "connection", "show"],
            text=True
        ).splitlines()

        for line in profiles:
            uuid, ctype = line.split(':', 1)
            if ctype == "802-11-wireless":
                subprocess.run(["nmcli", "connection", "delete", uuid],
                               check=False, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        log_debug(f"Could not list profiles: {e.stderr.strip()}")

    # ---- 3. add keyfile profile with stored PSK --------------------------
    try:
        subprocess.run([
            "nmcli", "connection", "add",
            "type", "wifi",
            "ifname", "wlan0",
            "con-name", ssid,
            "ssid", ssid,
            "wifi-sec.key-mgmt", "wpa-psk",
            "wifi-sec.psk", password,
            "802-11-wireless-security.psk-flags", "0",     # ← store on disk
            "connection.autoconnect", "yes"
        ], check=True, capture_output=True, text=True)

        subprocess.run(["nmcli", "connection", "reload"], check=True)
        subprocess.run(["nmcli", "connection", "up", ssid], check=True,
                       capture_output=True, text=True)

        log_debug(f"Activated Wi‑Fi connection '{ssid}' non‑interactively.")
    except subprocess.CalledProcessError as e:
        log_debug(f"nmcli error {e.returncode}: {e.stderr.strip() or e.stdout.strip()}")


def handle_orientation_change(data):
    """
    data: one of "normal", "90", "180", "270"
    1. Calls wlr-randr|grep|awk to grab the current mode@freq
    2. Writes out ~/.config/kanshi/config
    3. Restarts kanshi with that config
    """
    output = "HDMI-A-1"  # adjust if your output name is different

    # 1) grab current mode@freq
    try:
        mode = subprocess.check_output(
            "wlr-randr | grep '(current)' | awk '{print $1\"@\"$3}'",
            shell=True, text=True
        ).strip()
    except subprocess.CalledProcessError as e:
        log_debug(f"Failed to detect current mode: {e}")
        return

    # 2) write kanshi config
    cfg = f"""profile {{
    output {output} enable mode {mode} position 0,0 transform {data}
}}
"""
    cfg_path = os.path.expanduser("~/.config/kanshi/config")
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    with open(cfg_path, "w") as f:
        f.write(cfg)
    os.chmod(cfg_path, 0o600)
    log_debug(f"Wrote kanshi config: mode={mode}, transform={data}")

    # 3) restart kanshi so it picks up the new config
    subprocess.run(["killall", "kanshi"], check=False)
    subprocess.Popen(
        ["kanshi", "-c", cfg_path],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    log_debug(f"Rotated {output} → {data}° via kanshi")

def ble_callback(value, options):
    try:
        if value is None:                # ← ignore empty callback
            return

        # value can be a list of ints (BLE bytes) or a bytes object
        if isinstance(value, list):
            value_bytes = bytes(value)
        elif isinstance(value, (bytes, bytearray)):
            value_bytes = value
        else:
            log_debug(f"Unexpected BLE value type: {type(value)}")
            return

        message = value_bytes.decode("utf-8", errors="ignore").strip()
        log_debug("Received BLE data: " + message)

        if message.startswith("WIFI:"):
            handle_wifi_data(message[len("WIFI:"):].strip())
        elif message.startswith("ORIENT:"):
            handle_orientation_change(message[len("ORIENT:"):].strip())
        elif message == "REBOOT":
            log_debug("Reboot command received; rebooting now.")
            subprocess.run(["sudo", "reboot"], check=False)
        else:
            log_debug("Unknown BLE command received.")
    except Exception as e:
        log_debug("Error in ble_callback: " + str(e))

def start_gatt_server():
    global provisioning_char
    while True:
        try:
            dongles = adapter.Adapter.available()
            if not dongles:
                log_debug("No Bluetooth adapters available for GATT server!")
                time.sleep(5)
                continue
            dongle_addr = list(dongles)[0].address
            log_debug("Using Bluetooth adapter for GATT server: " + dongle_addr)
            
            ble_periph = peripheral.Peripheral(dongle_addr, local_name="PixelPaper")
            ble_periph.add_service(srv_id=1, uuid=PROVISIONING_SERVICE_UUID, primary=True)
            provisioning_char = ble_periph.add_characteristic(
                srv_id=1,
                chr_id=1,
                uuid=PROVISIONING_CHAR_UUID,
                value=[],  # Start with an empty value.
                notifying=False,
                flags=['write', 'write-without-response'],
                write_callback=ble_callback,
                read_callback=None,
                notify_callback=None
            )
            # Add a read-only serial characteristic containing the serial number.
            ble_periph.add_characteristic(
                srv_id=1,
                chr_id=2,
                uuid=SERIAL_CHAR_UUID,
                value=list(get_serial_number().encode()),
                notifying=False,
                flags=['read'],
                read_callback=lambda options: list(get_serial_number().encode()),
                write_callback=None,
                notify_callback=None
            )
            log_debug("Publishing GATT server for provisioning and serial...")
            ble_periph.publish()
            log_debug("GATT server event loop ended (likely due to disconnection).")
        except Exception as e:
            log_debug("Exception in start_gatt_server: " + str(e))
        log_debug("Restarting GATT server in 5 seconds...")
        time.sleep(5)

def start_gatt_server_thread():
    """Starts the GATT server in a background daemon thread."""
    t = threading.Thread(target=start_gatt_server, daemon=True)
    t.start()

# ── ttkbootstrap full-screen UI ─────────────────────────────────────────────
def _resize(event=None):
    short = min(root.winfo_width(), root.winfo_height())
    size = max(18, int(short * 0.15))
    status_lbl.configure(font=("Helvetica", size))

root = ttk.Window(themename="darkly")
root.withdraw()
root.title("Pixel Paper Status")
root.configure(background=BG)
root.attributes("-fullscreen", True)
root.bind("<Configure>", _resize)
root.config(cursor="none")

toast_mgr = ToastManager(root)

status_lbl = ttk.Label(
    root,
    text="Checking Wi-Fi…",
    font=("Helvetica", 48),
    bootstyle="secondary-inverse",
    anchor="center",
)
status_lbl.place(relx=0.5, rely=0.5, anchor="center")

root.deiconify()
disable_pairing()
start_gatt_server_thread()   # existing function import
_resize()
root.after(100, update_status)
root.mainloop()