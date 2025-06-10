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

# ── brand colours ─────────────────────────────────────────────────────────
BG_PRIMARY   = "#010101"
BG_SECONDARY = "#161616"
ACCENT       = "#1FC742"
ACCENT_DARK  = "#025B18"
TEXT_COLOR   = "#FFFFFF"

# ── provisioning UUIDs ─────────────────────────────────────────────────────
PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"
SERIAL_CHAR_UUID          = "12345678-1234-5678-1234-56789abcdef2"

FAIL_MAX   = 3
fail_count = 0
repo_updated = False

chromium_process = None
toasts = []  # keep track of active toast windows

# ── helpers ────────────────────────────────────────────────────────────────
def get_serial_number():
    try:
        with open('/proc/device-tree/serial-number', 'r') as f:
            serial = f.read().strip('\x00\n ')
        return "PX" + serial
    except:
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

def show_toast(message, duration=3000, fade_steps=10):
    """Create a small popup in top-right that fades in, stays, then fades out."""
    # create toast window
    toast = tk.Toplevel(root)
    toast.overrideredirect(True)
    toast.attributes('-topmost', True)
    toast.config(bg=BG_SECONDARY)
    # position it
    sw = root.winfo_screenwidth()
    margin = 20
    height = 50
    y_offset = margin + len(toasts)*(height + 5)
    toast.geometry(f"300x{height}+{sw-300-margin}+{y_offset}")
    # label
    lbl = tk.Label(toast, text=message, bg=BG_SECONDARY, fg=ACCENT, font=("Helvetica", 14))
    lbl.pack(expand=True, fill=tk.BOTH, padx=10)
    toasts.append(toast)

    def fade_in(step=0):
        alpha = step / fade_steps
        toast.attributes('-alpha', alpha)
        if step < fade_steps:
            toast.after(30, fade_in, step+1)
        else:
            toast.after(duration, fade_out, fade_steps)

    def fade_out(step):
        alpha = step / fade_steps
        toast.attributes('-alpha', alpha)
        if step > 0:
            toast.after(30, fade_out, step-1)
        else:
            toast.destroy()
            toasts.remove(toast)

    fade_in()

def log_debug(message):
    """Replaces old debug panel; shows as toast."""
    print(message)
    show_toast(message)

def disable_pairing():
    try:
        subprocess.run(
            ["bluetoothctl"],
            input="pairable no\nquit\n",
            text=True, capture_output=True, check=True
        )
    except Exception as e:
        log_debug("BT pairing disable failed: " + str(e))

def nm_reconnect():
    try:
        ssid = subprocess.check_output(
            ["nmcli", "-t", "-f", "NAME,TYPE,DEVICE,ACTIVE", "connection", "show", "--active"],
            text=True
        ).split(':')[0]
        subprocess.run(["nmcli", "connection", "up", ssid], check=False)
        log_debug(f"NM reconnect issued: {ssid}")
    except Exception as e:
        log_debug("nm_reconnect err: " + str(e))

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
            if chromium_process is None or chromium_process.poll() is not None:
                status_label.config(text="Wi-Fi OK – loading frame…")
                subprocess.run(["pkill", "-f", "chromium"], check=False)
                url = f"https://pixelpaper.com/frame.html?id={get_serial_number()}"
                chromium_process = subprocess.Popen(["chromium", "--kiosk", url])
        else:
            fail_count += 1
            log_debug("Wi-Fi down; retrying")
            if fail_count >= FAIL_MAX:
                status_label.config(text="Offline – waiting for network…")
                nm_reconnect()
        # schedule next check
    except Exception as e:
        log_debug("update_status error: " + str(e))
    finally:
        root.after(2000, update_status)

# ── BLE provisioning callbacks (unchanged) ─────────────────────────────────
def handle_wifi_data(data: str):
    log_debug("Handling Wi-Fi data: " + data)
    try:
        ssid, pass_part = data.split(';', 1)
        password = pass_part.split(':',1)[1]
    except ValueError:
        log_debug("Malformed payload; use SSID;PASS:pwd")
        return
    # wipe old profiles
    try:
        profiles = subprocess.check_output(
            ["nmcli","-t","-f","UUID,TYPE","connection","show"],
            text=True).splitlines()
        for line in profiles:
            uuid,ctype = line.split(':',1)
            if ctype=="802-11-wireless":
                subprocess.run(["nmcli","connection","delete",uuid], check=False)
    except subprocess.CalledProcessError as e:
        log_debug("List profiles failed: " + e.stderr.strip())
    # add new
    try:
        subprocess.run([
            "nmcli","connection","add","type","wifi","ifname","wlan0",
            "con-name",ssid,"ssid",ssid,
            "wifi-sec.key-mgmt","wpa-psk",
            "wifi-sec.psk",password,
            "802-11-wireless-security.psk-flags","0",
            "connection.autoconnect","yes"
        ], check=True, capture_output=True, text=True)
        subprocess.run(["nmcli","connection","reload"],check=True)
        subprocess.run(["nmcli","connection","up",ssid],check=True)
        log_debug(f"Activated Wi-Fi '{ssid}'")
    except subprocess.CalledProcessError as e:
        log_debug(f"nmcli error: {e.stderr.strip() or e.stdout.strip()}")

def handle_orientation_change(data):
    output = "HDMI-A-1"
    try:
        mode = subprocess.check_output(
            "wlr-randr | grep '(current)' | awk '{print $1\"@\"$3}'",
            shell=True, text=True).strip()
    except subprocess.CalledProcessError as e:
        log_debug("Mode detect failed: " + str(e))
        return
    cfg = f"""profile {{
    output {output} enable mode {mode} position 0,0 transform {data}
}}"""
    cfg_path = os.path.expanduser("~/.config/kanshi/config")
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    with open(cfg_path,"w") as f:
        f.write(cfg)
    os.chmod(cfg_path, 0o600)
    subprocess.run(["killall","kanshi"],check=False)
    subprocess.Popen(["kanshi","-c",cfg_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log_debug(f"Rotated {output} → {data}°")

def ble_callback(value, options):
    try:
        if value is None:
            return
        if isinstance(value, list):
            value_bytes = bytes(value)
        elif isinstance(value, (bytes,bytearray)):
            value_bytes = value
        else:
            log_debug("Unexpected BLE value type")
            return
        message = value_bytes.decode("utf-8",errors="ignore").strip()
        log_debug("BLE data: " + message)
        if message.startswith("WIFI:"):
            handle_wifi_data(message[len("WIFI:"):].strip())
        elif message.startswith("ORIENT:"):
            handle_orientation_change(message[len("ORIENT:"):].strip())
        elif message == "REBOOT":
            log_debug("Rebooting...")
            subprocess.run(["sudo","reboot"],check=False)
        else:
            log_debug("Unknown BLE command")
    except Exception as e:
        log_debug("ble_callback error: " + str(e))

def start_gatt_server():
    while True:
        try:
            dongles = adapter.Adapter.available()
            if not dongles:
                log_debug("No BT adapters!")
                time.sleep(5)
                continue
            dongle_addr = list(dongles)[0].address
            log_debug("Using adapter: " + dongle_addr)
            ble_periph = peripheral.Peripheral(dongle_addr, local_name="PixelPaper")
            ble_periph.add_service(srv_id=1, uuid=PROVISIONING_SERVICE_UUID, primary=True)
            ble_periph.add_characteristic(
                srv_id=1, chr_id=1, uuid=PROVISIONING_CHAR_UUID,
                value=[], flags=['write','write-without-response'],
                write_callback=ble_callback
            )
            ble_periph.add_characteristic(
                srv_id=1, chr_id=2, uuid=SERIAL_CHAR_UUID,
                value=list(get_serial_number().encode()),
                flags=['read']
            )
            log_debug("Publishing GATT server…")
            ble_periph.publish()
            log_debug("GATT loop ended")
        except Exception as e:
            log_debug("GATT error: " + str(e))
        log_debug("Restarting GATT in 5s…")
        time.sleep(5)

def start_gatt_server_thread():
    threading.Thread(target=start_gatt_server, daemon=True).start()

# ── UI setup ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    root = tk.Tk()
    root.title("PixelPaper Frame")
    root.configure(bg=BG_PRIMARY)
    root.attributes('-fullscreen', True)

    # responsive status label
    status_label = tk.Label(
        root,
        text="Checking network…",
        bg=BG_PRIMARY,
        fg=ACCENT,
        font=("Helvetica", 48),
        wraplength=root.winfo_screenwidth()*0.8,
        justify='center'
    )
    status_label.place(relx=0.5, rely=0.5, anchor='center')

    def on_resize(event):
        # adjust font size to 10% of smaller dimension
        size = max(16, int(min(event.width, event.height) * 0.08))
        status_label.config(font=("Helvetica", size), wraplength=event.width * 0.8)

    root.bind('<Configure>', on_resize)

    disable_pairing()
    start_gatt_server_thread()
    # first status check kicks off its own loop
    root.after(500, update_status)

    root.mainloop()
