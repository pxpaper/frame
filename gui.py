#!/usr/bin/env python3
import tkinter as tk
import socket
import subprocess
import time
import threading
import os
from bluezero import adapter, peripheral
import math

# Import update_repo so we can refresh once Wi-Fi is up
import launch

# --- UI Configuration & Brand Colors ---
BRAND_COLORS = {
    "background": "#161616",
    "foreground": "#FFFFFF",
    "accent": "#1FC742",
    "accent_dark": "#025B18",
    "almost_black": "#010101"
}
TOAST_LIFETIME_MS = 5000  # Notifications disappear after 5 seconds

# --- Global State ---
app = None
active_toasts = []
repo_updated = False  # Run update only once
chromium_process = None
fail_count = 0
FAIL_MAX = 3

# UUIDs for custom provisioning service and characteristics.
PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"
SERIAL_CHAR_UUID          = "12345678-1234-5678-1234-56789abcdef2"

# ─── UI Classes ──────────────────────────────────────────────────────────

class Toast:
    """A pop-up notification window that self-destructs."""
    def __init__(self, parent, message):
        self.parent = parent
        self.window = tk.Toplevel(parent)
        self.window.overrideredirect(True)  # No title bar or borders
        self.window.attributes("-alpha", 0.95) # Slightly transparent

        label = tk.Label(
            self.window, text=message,
            bg=BRAND_COLORS["almost_black"], fg=BRAND_COLORS["foreground"],
            font=("Helvetica", 12, "bold"),
            padx=15, pady=10,
            wraplength=300, justify=tk.LEFT
        )
        label.pack()

        self.position_and_show()
        self.window.after(TOAST_LIFETIME_MS, self.destroy)

    def position_and_show(self):
        self.parent.update_idletasks()
        parent_x = self.parent.winfo_x()
        parent_width = self.parent.winfo_width()
        self.window.update_idletasks()
        win_width = self.window.winfo_width()
        
        # Calculate vertical offset based on existing toasts
        vertical_offset = sum(t.window.winfo_height() + 10 for t in active_toasts)
        
        x = parent_x + parent_width - win_width - 10
        y = parent_x + 10 + vertical_offset
        self.window.geometry(f"+{x}+{y}")
        active_toasts.append(self)

    def destroy(self):
        active_toasts.remove(self)
        self.window.destroy()
        # Reposition remaining toasts
        offset = 0
        for t in active_toasts:
            parent_x = t.parent.winfo_x()
            parent_width = t.parent.winfo_width()
            win_width = t.window.winfo_width()
            x = parent_x + parent_width - win_width - 10
            y = parent_x + 10 + offset
            t.window.geometry(f"+{x}+{y}")
            offset += t.window.winfo_height() + 10

def show_toast(message):
    """Creates a toast notification. Replaces the old log_debug."""
    print(message) # Also print to console for systemd logs
    if root:
       Toast(root, message)

class StatusUI:
    """The main full-screen UI for the application."""
    def __init__(self, parent):
        self.parent = parent
        self.parent.configure(bg=BRAND_COLORS["background"])
        self.parent.attributes('-fullscreen', True)

        self.canvas = tk.Canvas(
            parent, bg=BRAND_COLORS["background"],
            highlightthickness=0, width=200, height=200
        )
        self.status_label = tk.Label(
            parent, text="Initializing...",
            font=("Helvetica", 32, "bold"),
            bg=BRAND_COLORS["background"], fg=BRAND_COLORS["foreground"]
        )

        self.canvas.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        self.status_label.place(relx=0.5, rely=0.5, y=150, anchor=tk.CENTER)
        
        # Animation variables
        self.angle = 0
        self.pulse_radius = 60
        self.pulse_direction = 1

        self.animate()

    def set_status(self, text):
        self.status_label.config(text=text)

    def animate(self):
        self.canvas.delete("all")
        
        # Pulsating inner circle
        self.pulse_radius += 0.5 * self.pulse_direction
        if self.pulse_radius > 70 or self.pulse_radius < 60:
            self.pulse_direction *= -1
            
        r = self.pulse_radius
        self.canvas.create_oval(100-r, 100-r, 100+r, 100+r, 
                                fill=BRAND_COLORS["accent_dark"], width=0)

        # Rotating outer arc
        self.angle = (self.angle + 4) % 360
        self.canvas.create_arc(
            20, 20, 180, 180,
            start=self.angle, extent=120,
            style=tk.ARC, outline=BRAND_COLORS["accent"],
            width=8
        )
        self.parent.after(20, self.animate)

# ─── Backend & System Functions (mostly unchanged) ───────────────────────

def get_serial_number():
    try:
        with open('/proc/device-tree/serial-number', 'r') as f:
            serial = f.read().strip('\x00\n ')
        return "PX" + serial
    except Exception:
        return "PXunknown"

def disable_pairing():
    try:
        subprocess.run(
            ["bluetoothctl"],
            input="pairable no\nquit\n", text=True,
            capture_output=True, check=True
        )
    except Exception as e:
        show_toast("Failed to disable pairing: " + str(e))

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
        show_toast(f"nmcli reconnect issued for {ssid}")
    except Exception as e:
        show_toast(f"nm_reconnect err: {e}")

def update_status():
    global chromium_process, fail_count, repo_updated, app
    
    # Schedule the next check
    root.after(10000, update_status)

    try:
        if check_wifi_connection():
            if fail_count > 0: # If we were previously offline
                show_toast("Wi-Fi reconnected")
            fail_count = 0
            
            # If repo hasn't been updated yet, do it now in a thread
            if not repo_updated:
                show_toast("Network online, checking for updates...")
                threading.Thread(target=launch.update_repo, daemon=True).start()
                repo_updated = True

            # (Re)start Chromium if it’s not running
            if chromium_process is None or chromium_process.poll() is not None:
                app.set_status("Starting Frame")
                subprocess.run(["pkill", "-f", "chromium"], check=False)
                url = f"https://pixelpaper.com/frame.html?id={get_serial_number()}"
                chromium_process = subprocess.Popen(["chromium", "--kiosk", url])
        else:
            fail_count += 1
            if fail_count == FAIL_MAX: # Only show message once we're sure
                show_toast("Wi-Fi connection is down")
                app.set_status("Wi-Fi Offline")
                if chromium_process:
                    chromium_process.terminate()
                    chromium_process = None
                nm_reconnect() # Attempt to bring connection back up

    except Exception as e:
        show_toast(f"update_status error: {e}")

def handle_wifi_data(data: str):
    show_toast("Received new Wi-Fi credentials")
    # ... (rest of the function is identical to the original)
    try:
        ssid, pass_part = data.split(';', 1)
        password = pass_part.split(':', 1)[1]
    except ValueError:
        show_toast("Wi-Fi payload malformed")
        return
    try:
        profiles = subprocess.check_output(
            ["nmcli", "-t", "-f", "UUID,TYPE", "connection", "show"], text=True
        ).splitlines()
        for line in profiles:
            uuid, ctype = line.split(':', 1)
            if ctype == "802-11-wireless":
                subprocess.run(["nmcli", "connection", "delete", uuid], check=False)
    except Exception as e:
        show_toast(f"Could not clear profiles: {e}")
    try:
        subprocess.run([
            "nmcli", "connection", "add", "type", "wifi", "ifname", "wlan0",
            "con-name", ssid, "ssid", ssid, "wifi-sec.key-mgmt", "wpa-psk",
            "wifi-sec.psk", password, "802-11-wireless-security.psk-flags", "0",
            "connection.autoconnect", "yes"
        ], check=True, capture_output=True, text=True)
        subprocess.run(["nmcli", "connection", "up", ssid], check=True)
        show_toast(f"Connected to Wi-Fi '{ssid}'")
        app.set_status("Connecting...")
    except subprocess.CalledProcessError as e:
        show_toast(f"nmcli error: {e.stderr.strip() or e.stdout.strip()}")

def handle_orientation_change(data):
    # ... (function is identical to the original)
    output = "HDMI-A-1"
    try:
        mode = subprocess.check_output(
            "wlr-randr | grep '(current)' | awk '{print $1\"@\"$3}'", shell=True, text=True
        ).strip()
    except subprocess.CalledProcessError as e:
        show_toast(f"Failed to detect mode: {e}")
        return
    cfg = f"profile {{ output {output} enable mode {mode} position 0,0 transform {data} }}"
    cfg_path = os.path.expanduser("~/.config/kanshi/config")
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    with open(cfg_path, "w") as f: f.write(cfg)
    os.chmod(cfg_path, 0o600)
    subprocess.run(["killall", "kanshi"], check=False)
    subprocess.Popen(["kanshi", "-c", cfg_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    show_toast(f"Rotated screen to {data}°")

def ble_callback(value, options):
    # ... (function is identical to the original, but uses show_toast)
    try:
        if value is None: return
        if isinstance(value, list): value_bytes = bytes(value)
        elif isinstance(value, (bytes, bytearray)): value_bytes = value
        else:
            show_toast(f"Unexpected BLE value type: {type(value)}")
            return
        message = value_bytes.decode("utf-8", errors="ignore").strip()
        show_toast("Received BLE data: " + message)
        if message.startswith("WIFI:"):
            handle_wifi_data(message[len("WIFI:"):].strip())
        elif message.startswith("ORIENT:"):
            handle_orientation_change(message[len("ORIENT:"):].strip())
        elif message == "REBOOT":
            show_toast("Reboot command received.")
            subprocess.run(["sudo", "reboot"], check=False)
        else:
            show_toast("Unknown BLE command received.")
    except Exception as e:
        show_toast("Error in ble_callback: " + str(e))

def start_gatt_server():
    # ... (function is identical to the original, but uses show_toast)
    while True:
        try:
            dongles = adapter.Adapter.available()
            if not dongles:
                show_toast("No Bluetooth adapters available!")
                time.sleep(5)
                continue
            dongle_addr = list(dongles)[0].address
            show_toast("Starting BLE Service on " + dongle_addr)
            ble_periph = peripheral.Peripheral(dongle_addr, local_name="PixelPaper")
            ble_periph.add_service(srv_id=1, uuid=PROVISIONING_SERVICE_UUID, primary=True)
            ble_periph.add_characteristic(
                srv_id=1, chr_id=1, uuid=PROVISIONING_CHAR_UUID, value=[], notifying=False,
                flags=['write', 'write-without-response'], write_callback=ble_callback,
            )
            ble_periph.add_characteristic(
                srv_id=1, chr_id=2, uuid=SERIAL_CHAR_UUID, value=list(get_serial_number().encode()),
                notifying=False, flags=['read'],
                read_callback=lambda options: list(get_serial_number().encode()),
            )
            ble_periph.publish()
            show_toast("BLE event loop ended. Restarting...")
        except Exception as e:
            show_toast("GATT server error: " + str(e))
        time.sleep(5)

def start_gatt_server_thread():
    threading.Thread(target=start_gatt_server, daemon=True).start()

# ─── Main Execution ──────────────────────────────────────────────────────
if __name__ == '__main__':
    root = tk.Tk()
    root.title("Frame Status")
    
    app = StatusUI(root)
    app.set_status("Checking Wi-Fi...")

    disable_pairing()
    start_gatt_server_thread()
    
    # Start the first status check after a short delay
    root.after(1000, update_status)

    root.mainloop()