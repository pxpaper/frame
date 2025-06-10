#!/usr/bin/env python3
"""
gui.py – full-screen status UI for Pixel Paper frames
─────────────────────────────────────────────────────
• Keeps all original BLE, Wi-Fi, repo-update logic
• Adds modern eye-friendly UI with ttkbootstrap
"""
import os
import socket
import subprocess
import threading
import time
import tkinter as tk
from itertools import cycle

from ttkbootstrap import Style
from ttkbootstrap.toast import ToastNotification

# ── import launch helpers (update_repo etc.) ─────────────
import launch                                      # noqa: E402  (local import)

# ─────────────────────────────────────────────────────────
#                     BRAND COLOURS
# ─────────────────────────────────────────────────────────
CLR_BG       = "#010101"
CLR_BG_ALT   = "#161616"
CLR_PRIMARY  = "#1FC742"
CLR_PRIMARY_DK = "#025B18"
FONT_FAMILY  = "Helvetica"

# ─────────────────────────────────────────────────────────
#                    GLOBAL STATE
# ─────────────────────────────────────────────────────────
PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"
SERIAL_CHAR_UUID          = "12345678-1234-5678-1234-56789abcdef2"

FAIL_MAX    = 3               # before we attempt nmcli reconnect
fail_count  = 0
repo_updated = False
chromium_process = None

debug_cycle  = cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
toast_queue  = []             # outstanding ToastNotification objs

# ─────────────────────────────────────────────────────────
#                 UTILITY / SYSTEM HELPERS
# ─────────────────────────────────────────────────────────
def get_serial_number() -> str:
    try:
        with open("/proc/device-tree/serial-number") as f:
            serial = f.read().strip("\x00\n ")
        return "PX" + serial
    except Exception:
        return "PXunknown"


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


# ─────────────────────────────────────────────────────────
#                   GUI / STYLE HELPERS
# ─────────────────────────────────────────────────────────
style = Style("darkly")                 # base theme
# override palette for brand consistency
style.configure(".", background=CLR_BG, foreground="#ffffff")
style.configure("TLabel", font=(FONT_FAMILY, 48, "bold"))
style.configure("Status.TLabel", background=CLR_BG, foreground=CLR_PRIMARY)
style.configure("ToastNotification", background=CLR_BG_ALT, foreground="#ffffff")

root = style.master
root.attributes("-fullscreen", True)
root.title("Pixel Paper Frame Status")

# central status banner
status_var = tk.StringVar(value="Checking Wi-Fi…")
status_lbl = tk.Label(root, textvariable=status_var,
                      style="Status.TLabel", anchor="center")
status_lbl.place(relx=.5, rely=.5, anchor="center")


def toast(message: str, sec: int = 4):
    """Non-blocking toast in top-right corner."""
    note = ToastNotification(
        title="",
        message=message,
        duration=sec * 1000,
        bootstyle=(CLR_PRIMARY, "inverse")  # primary bg, white text
    )
    toast_queue.append(note)
    note.show_toast(top=15 + 60 * (len(toast_queue) - 1), right=20)  # stack
    # prune when closed
    root.after(sec * 1000 + 500, lambda: toast_queue.remove(note)
                                     if note in toast_queue else None)


def log_debug(msg: str):
    """Replace debug_text pane with toasts."""
    print(msg)
    toast(msg, sec=4)


# ─────────────────────────────────────────────────────────
#               CONNECTIVITY / STATUS LOOP
# ─────────────────────────────────────────────────────────
def start_chromium():
    global chromium_process
    subprocess.run(["pkill", "-f", "chromium"], check=False)
    url = f"https://pixelpaper.com/frame.html?id={get_serial_number()}"
    chromium_process = subprocess.Popen(
        ["chromium", "--kiosk", url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    log_debug("Launched Chromium kiosk")


def update_status():
    """Periodic loop – runs every 5 s."""
    global fail_count, repo_updated

    online = check_wifi_connection()
    spinner = next(debug_cycle)  # neat animated glyph
    if online:
        if fail_count:
            fail_count = 0
        if not repo_updated:
            threading.Thread(target=launch.update_repo, daemon=True).start()
            repo_updated = True
            log_debug("Repo updated after connectivity established")

        # Ensure Chromium is running
        if chromium_process is None or chromium_process.poll() is not None:
            status_var.set("Wi-Fi OK — starting frame " + spinner)
            start_chromium()
        else:
            status_var.set("Frame running " + spinner)
    else:
        status_var.set("Waiting for Wi-Fi… " + spinner)
        fail_count += 1
        if fail_count >= FAIL_MAX:
            nm_reconnect()
            fail_count = 0

    root.after(5000, update_status)      # reschedule


# ─────────────────────────────────────────────────────────
#                   BLE / GATT SERVER
# ─────────────────────────────────────────────────────────
# We keep all original BLE plumbing untouched, but replace log calls with
# the new toast-based log_debug() so errors surface to the user nicely.
from bluezero import adapter, peripheral          # noqa: E402


def ble_callback(value, options):
    # (exactly the same decode & dispatch code as before)
    try:
        if value is None:
            return
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
    while True:
        try:
            dongles = adapter.Adapter.available()
            if not dongles:
                log_debug("No Bluetooth adapters available for GATT server!")
                time.sleep(5)
                continue
            dongle_addr = list(dongles)[0].address
            log_debug("Using Bluetooth adapter: " + dongle_addr)

            ble_periph = peripheral.Peripheral(dongle_addr, local_name="PixelPaper")
            ble_periph.add_service(srv_id=1, uuid=PROVISIONING_SERVICE_UUID, primary=True)
            prov_char = ble_periph.add_characteristic(
                srv_id=1,
                chr_id=1,
                uuid=PROVISIONING_CHAR_UUID,
                value=[],
                notifying=False,
                flags=['write', 'write-without-response'],
                write_callback=ble_callback
            )
            ble_periph.add_characteristic(
                srv_id=1,
                chr_id=2,
                uuid=SERIAL_CHAR_UUID,
                value=list(get_serial_number().encode()),
                flags=['read'],
                read_callback=lambda options: list(get_serial_number().encode())
            )
            log_debug("Publishing GATT server...")
            ble_periph.publish()
            log_debug("GATT server loop ended (disconnect?)")
        except Exception as e:
            log_debug("Exception in GATT server: " + str(e))
        log_debug("Restarting GATT server in 5 s…")
        time.sleep(5)


def start_gatt_server_thread():
    t = threading.Thread(target=start_gatt_server, daemon=True)
    t.start()


# ─────────────────────────────────────────────────────────
#                 WIFI HELPERS (unchanged logic)
# ─────────────────────────────────────────────────────────
def handle_wifi_data(data: str):
    # (identical implementation – omitted for brevity)
    log_debug("Handling Wi-Fi data: " + data)
    try:
        ssid, pass_part = data.split(';', 1)
        password = pass_part.split(':', 1)[1]
    except ValueError:
        log_debug("WiFi payload malformed; expected SSID;PASS:pwd")
        return

    # wipe old profiles …
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

    # add profile and connect …
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
    # (identical implementation – omitted for brevity)
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
    subprocess.Popen(
        ["kanshi", "-c", cfg_path],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    log_debug(f"Rotated {output} → {data}° via kanshi")


# ─────────────────────────────────────────────────────────
#                           MAIN
# ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    disable_pairing()
    start_gatt_server_thread()
    update_status()           # kick-off periodic loop
    root.mainloop()
