#!/usr/bin/env python3
import tkinter as tk
import socket
import subprocess
import time
import threading
import os
from bluezero import adapter, peripheral

# Import update_repo so we can refresh once Wi-Fi is up
import launch

# ── style constants ────────────────────────────────────────────────────────
BG_COLOR       = "#010101"
PRIMARY_GREEN  = "#1FC742"
DARK_GREEN     = "#025B18"
ACCENT_DARK    = "#161616"
TOAST_BG       = ACCENT_DARK
TOAST_FG       = PRIMARY_GREEN
TOAST_BORDER   = DARK_GREEN
TOAST_DURATION = 5000   # milliseconds
TOAST_MARGIN   = 10     # px from edges
TOAST_SPACING  = 5      # px between toasts

# UUIDs for provisioning
PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID   = "12345678-1234-5678-1234-56789abcdef1"
SERIAL_CHAR_UUID         = "12345678-1234-5678-1234-56789abcdef2"

FAIL_MAX   = 3
fail_count = 0
repo_updated = False

chromium_process = None
toast_labels = []

def get_serial_number():
    try:
        with open('/proc/device-tree/serial-number', 'r') as f:
            serial = f.read().strip('\x00\n ')
        return "PX" + serial
    except Exception:
        return "PXunknown"

def show_toast(message: str):
    """Create a temporary pop-up in the top-right that slides in and self-destructs."""
    # Create label
    lbl = tk.Label(root,
        text=message,
        font=("Helvetica", 14),
        bg=TOAST_BG,
        fg=TOAST_FG,
        bd=1,
        relief="solid",
        highlightbackground=TOAST_BORDER,
        highlightthickness=1,
        wraplength=300,
        justify="left"
    )
    toast_labels.append(lbl)
    # Position off-screen (to the right)
    root.update_idletasks()
    win_w = root.winfo_width()
    lbl.place(x=win_w + 10, y=TOAST_MARGIN)
    _reposition_toasts()
    _animate_slide_in(lbl, win_w - TOAST_MARGIN - lbl.winfo_reqwidth())

    # Schedule removal
    root.after(TOAST_DURATION, lambda: _remove_toast(lbl))

def _reposition_toasts():
    """Stack all active toast_labels from the top-right downward."""
    for idx, lbl in enumerate(toast_labels):
        x = root.winfo_width() - TOAST_MARGIN - lbl.winfo_reqwidth()
        y = TOAST_MARGIN + idx * (lbl.winfo_reqheight() + TOAST_SPACING)
        lbl.place_configure(x=x, y=y)

def _animate_slide_in(lbl, target_x, duration=300):
    """Slide the label from its current x to target_x over duration ms."""
    steps = 10
    delay = int(duration / steps)
    start_x = lbl.winfo_x()
    dx = (start_x - target_x) / steps

    def step(i):
        new_x = start_x - dx * (i + 1)
        lbl.place_configure(x=new_x)
        if i + 1 < steps:
            root.after(delay, lambda: step(i + 1))

    step(0)

def log_debug(message):
    """Redirect old debug calls into modern toasts."""
    print(message)                   # still print to console
    show_toast(message)

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
            if fail_count:
                fail_count = 0
                if not repo_updated:
                    threading.Thread(target=launch.update_repo, daemon=True).start()
                    repo_updated = True
                    log_debug("Repository update triggered.")

            # launch Chromium if needed
            if chromium_process is None or chromium_process.poll() is not None:
                log_debug("Wi-Fi OK → starting frame")
                subprocess.run(["pkill", "-f", "chromium"], check=False)
                url = f"https://pixelpaper.com/frame.html?id={get_serial_number()}"
                chromium_process = subprocess.Popen(["chromium", "--kiosk", url])
        else:
            log_debug("Wi-Fi down, retrying soon")

    except Exception as e:
        log_debug(f"update_status error: {e}")
    finally:
        # re-check every 10 s
        root.after(10_000, update_status)

def handle_wifi_data(data: str):
    log_debug("Handling WiFi data: " + data)
    try:
        ssid, pass_part = data.split(';', 1)
        password = pass_part.split(':', 1)[1]
    except ValueError:
        log_debug("WiFi payload malformed; expected SSID;PASS:pwd")
        return

    # delete existing Wi-Fi profiles
    try:
        profiles = subprocess.check_output(
            ["nmcli", "-t", "-f", "UUID,TYPE", "connection", "show"],
            text=True
        ).splitlines()
        for line in profiles:
            uuid, ctype = line.split(':', 1)
            if ctype == "802-11-wireless":
                subprocess.run(["nmcli", "connection", "delete", uuid], check=False)
    except subprocess.CalledProcessError as e:
        log_debug(f"Could not list profiles: {e.stderr.strip()}")

    # add new profile
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
        subprocess.run(["nmcli", "connection", "up", ssid], check=True, capture_output=True, text=True)
        log_debug(f"Activated Wi-Fi '{ssid}' without prompt.")
    except subprocess.CalledProcessError as e:
        log_debug(f"nmcli error {e.returncode}: {e.stderr.strip() or e.stdout.strip()}")

def handle_orientation_change(data):
    output = "HDMI-A-1"  # adjust as needed
    try:
        mode = subprocess.check_output(
            "wlr-randr | grep '(current)' | awk '{print $1\"@\"$3}'",
            shell=True, text=True
        ).strip()
    except subprocess.CalledProcessError as e:
        log_debug(f"Failed to detect mode: {e}")
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
    subprocess.Popen(["kanshi", "-c", cfg_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log_debug(f"Rotated {output} → {data}°")

def ble_callback(value, options):
    try:
        if value is None:
            return
        value_bytes = bytes(value) if isinstance(value, (bytes, bytearray)) else bytes(value)
        message = value_bytes.decode("utf-8", errors="ignore").strip()
        log_debug("Received BLE data: " + message)
        if message.startswith("WIFI:"):
            handle_wifi_data(message[len("WIFI:"):].strip())
        elif message.startswith("ORIENT:"):
            handle_orientation_change(message[len("ORIENT:"):].strip())
        elif message == "REBOOT":
            log_debug("Reboot command received.")
            subprocess.run(["sudo", "reboot"], check=False)
        else:
            log_debug("Unknown BLE command.")
    except Exception as e:
        log_debug("Error in BLE callback: " + str(e))

def start_gatt_server():
    while True:
        try:
            dongles = adapter.Adapter.available()
            if not dongles:
                log_debug("No Bluetooth adapters!")
                time.sleep(5)
                continue
            dongle_addr = list(dongles)[0].address
            ble_periph = peripheral.Peripheral(dongle_addr, local_name="PixelPaper")
            ble_periph.add_service(srv_id=1, uuid=PROVISIONING_SERVICE_UUID, primary=True)
            ble_periph.add_characteristic(
                srv_id=1, chr_id=1, uuid=PROVISIONING_CHAR_UUID,
                value=[], notifying=False,
                flags=['write','write-without-response'],
                write_callback=ble_callback
            )
            ble_periph.add_characteristic(
                srv_id=1, chr_id=2, uuid=SERIAL_CHAR_UUID,
                value=list(get_serial_number().encode()),
                flags=['read'],
                read_callback=lambda opts: list(get_serial_number().encode())
            )
            log_debug("Publishing GATT server...")
            ble_periph.publish()
            log_debug("GATT event loop ended.")
        except Exception as e:
            log_debug("GATT server exception: " + str(e))
        log_debug("Restarting GATT server in 5s...")
        time.sleep(5)

def start_gatt_server_thread():
    t = threading.Thread(target=start_gatt_server, daemon=True)
    t.start()

# ── Main GUI ────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    root = tk.Tk()
    root.title("PixelPaper Setup")
    root.configure(bg=BG_COLOR)
    root.attributes('-fullscreen', True)

    # Central status label
    status_label = tk.Label(
        root,
        text="Checking Wi-Fi…",
        font=("Helvetica", 56),
        bg=BG_COLOR,
        fg=PRIMARY_GREEN
    )
    status_label.place(relx=0.5, rely=0.5, anchor="center")

    # Replace text updates with style + animation
    def set_status(text: str):
        status_label.config(text=text)
        # (Optionally add a quick fade or scale animation here)

    # Hook into update_status to change the central text
    original_update_status = update_status
    def wrapped_update_status():
        try:
            if check_wifi_connection():
                set_status("Wi-Fi OK — launching frame")
            else:
                set_status("Waiting for Wi-Fi…")
        finally:
            original_update_status()
    update_status = wrapped_update_status

    disable_pairing()
    start_gatt_server_thread()
    update_status()

    root.mainloop()
