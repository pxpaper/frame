#!/usr/bin/env python3
import tkinter as tk
from tkinter import font as tkFont
import socket
import subprocess
import time
import threading
import os
from bluezero import adapter, peripheral

# Import update_repo so we can refresh once Wi-Fi is up
import launch

# ── constants ────────────────────────────────────────────────────────────

# Brand Colors
COLOR_BACKGROUND = "#161616"
COLOR_FOREGROUND = "#1FC742"
COLOR_TOAST_BG   = "#010101"
COLOR_TOAST_FG   = "#FFFFFF"

# UUIDs for custom provisioning service and characteristics.
PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"
SERIAL_CHAR_UUID          = "12345678-1234-5678-1234-56789abcdef2"

# ── global state ─────────────────────────────────────────────────────────
repo_updated = False
fail_count = 0
chromium_process = None
active_toasts = []

# ── core backend logic (functionality unchanged) ─────────────────────────

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
            input="pairable no\nquit\n",
            text=True,
            capture_output=True,
            check=True
        )
    except Exception as e:
        log_toast("Failed to disable pairing: " + str(e))

def check_wifi_connection(retries: int = 2) -> bool:
    for _ in range(retries):
        try:
            s = socket.create_connection(("8.8.8.8", 53), timeout=3)
            s.close()
            return True
        except OSError:
            time.sleep(0.3)
    return False

def update_status():
    global chromium_process, fail_count, repo_updated
    try:
        up = check_wifi_connection()
        if up:
            if fail_count > 0:
                log_toast("Wi-Fi connection restored.")
            fail_count = 0

            # If this is the first time we're online, trigger an update
            if not repo_updated:
                log_toast("Network online. Checking for updates...")
                threading.Thread(target=launch.update_repo, daemon=True).start()
                repo_updated = True

            # (Re)start Chromium if it’s not running
            if chromium_process is None or chromium_process.poll() is not None:
                update_main_status("Starting Frame", animate=False)
                subprocess.run(["pkill", "-f", "chromium"], check=False)
                url = f"https://pixelpaper.com/frame.html?id={get_serial_number()}"
                chromium_process = subprocess.Popen(["chromium", "--kiosk", url])
                # After launching, we can hide the status window
                root.withdraw()

        else:
            # Not online, ensure the status window is visible
            if root.state() == 'withdrawn':
                root.deiconify()
            fail_count += 1
            log_toast("Wi-Fi down, will retry...", "WIFI_RETRY")
            update_main_status("Searching for Wi-Fi")

    except Exception as e:
        log_toast(f"Status update error: {e}")
    finally:
        # Check again in 10 seconds
        root.after(10000, update_status)

def handle_wifi_data(data: str):
    log_toast("Received new Wi-Fi credentials.")
    try:
        ssid, pass_part = data.split(';', 1)
        password = pass_part.split(':', 1)[1]
    except (ValueError, IndexError):
        log_toast("Error: Wi-Fi data was malformed.")
        return

    try:
        # Wipe existing wireless profiles for simplicity
        profiles = subprocess.check_output(["nmcli", "-t", "-f", "UUID,TYPE", "connection", "show"], text=True).splitlines()
        for line in profiles:
            if "802-11-wireless" in line:
                uuid = line.split(':')[0]
                subprocess.run(["nmcli", "connection", "delete", uuid], check=False)
        log_toast("Cleared old Wi-Fi profiles.")

        # Add new profile
        subprocess.run([
            "nmcli", "connection", "add", "type", "wifi", "ifname", "wlan0",
            "con-name", ssid, "ssid", ssid, "wifi-sec.key-mgmt", "wpa-psk",
            "wifi-sec.psk", password, "connection.autoconnect", "yes"
        ], check=True, capture_output=True, text=True)

        log_toast(f"Connecting to '{ssid}'...")
        subprocess.run(["nmcli", "connection", "up", ssid], check=True)

    except subprocess.CalledProcessError as e:
        log_toast(f"nmcli error: {e.stderr.strip()}", "NMCLI_ERROR")

def handle_orientation_change(data):
    # This function remains the same as the original
    output = "HDMI-A-1" # Adjust if your output name is different
    try:
        mode = subprocess.check_output(
            "wlr-randr | grep '(current)' | awk '{print $1\"@\"$3}'",
            shell=True, text=True
        ).strip()
    except subprocess.CalledProcessError as e:
        log_toast(f"Could not detect display mode: {e}")
        return

    cfg = f"profile {{ output {output} enable mode {mode} position 0,0 transform {data} }}"
    cfg_path = os.path.expanduser("~/.config/kanshi/config")
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    with open(cfg_path, "w") as f:
        f.write(cfg)
    os.chmod(cfg_path, 0o600)

    subprocess.run(["killall", "kanshi"], check=False)
    subprocess.Popen(["kanshi", "-c", cfg_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log_toast(f"Screen rotated to {data} degrees.")

def ble_callback(value, options):
    if not value: return
    try:
        value_bytes = bytes(value)
        message = value_bytes.decode("utf-8", errors="ignore").strip()
        if not message: return

        log_toast(f"Received BLE command: {message.split(':')[0]}")

        if message.startswith("WIFI:"):
            handle_wifi_data(message[len("WIFI:"):].strip())
        elif message.startswith("ORIENT:"):
            handle_orientation_change(message[len("ORIENT:"):].strip())
        elif message == "REBOOT":
            log_toast("Rebooting now...")
            subprocess.run(["sudo", "reboot"], check=False)
        else:
            log_toast("Unknown BLE command.")
    except Exception as e:
        log_toast(f"BLE Error: {e}", "BLE_ERROR")

def start_gatt_server():
    while True:
        try:
            dongle = adapter.Adapter.available()[0]
            log_toast(f"Starting BLE server on {dongle.address}", "BLE_INIT")
            
            ble_periph = peripheral.Peripheral(dongle.address, local_name="PixelPaper")
            ble_periph.add_service(srv_id=1, uuid=PROVISIONING_SERVICE_UUID, primary=True)
            
            # Writeable characteristic for provisioning
            ble_periph.add_characteristic(
                srv_id=1, chr_id=1, uuid=PROVISIONING_CHAR_UUID, value=[], notifying=False,
                flags=['write', 'write-without-response'], write_callback=ble_callback
            )
            # Readable characteristic for serial number
            ble_periph.add_characteristic(
                srv_id=1, chr_id=2, uuid=SERIAL_CHAR_UUID, value=list(get_serial_number().encode()),
                notifying=False, flags=['read']
            )
            
            ble_periph.publish()
        except Exception as e:
            log_toast(f"GATT server crashed: {e}", "GATT_ERROR")
            log_toast("Restarting BLE server in 5s...")
            time.sleep(5)

# ── new ui components ────────────────────────────────────────────────────

def log_toast(message: str, toast_id: str = None):
    """
    Displays a short-lived, self-stacking notification in the top-right corner.
    An ID can be provided to prevent duplicate messages from spamming the screen.
    """
    # Prevent duplicate toasts if an ID is given
    if toast_id and any(t.toast_id == toast_id for t in active_toasts):
        return

    # This needs to run on the main thread
    root.after(0, _create_toast, message, toast_id)

def _create_toast(message: str, toast_id: str):
    toast = tk.Toplevel(root)
    toast.toast_id = toast_id
    toast.overrideredirect(True) # No title bar or border
    toast.geometry(f"+{root.winfo_screenwidth() - 410}+{30 + (len(active_toasts) * 60)}")
    toast.config(bg=COLOR_TOAST_BG, borderwidth=1, relief="solid")
    
    label = tk.Label(toast, text=message, bg=COLOR_TOAST_BG, fg=COLOR_TOAST_FG,
                     font=("Helvetica", 14), wraplength=380, justify=tk.LEFT,
                     padx=15, pady=10)
    label.pack()
    
    active_toasts.append(toast)
    toast.after(5000, lambda: _destroy_toast(toast))

def _destroy_toast(toast):
    if toast in active_toasts:
        active_toasts.remove(toast)
        toast.destroy()
        # Reposition remaining toasts
        for i, t in enumerate(active_toasts):
            t.geometry(f"+{root.winfo_screenwidth() - 410}+{30 + (i * 60)}")

def update_main_status(text: str, animate: bool = True):
    """Updates the central status message and controls the loading animation."""
    status_label.config(text=text)
    if animate:
        animation_label.place(relx=0.5, rely=0.65, anchor='center')
        _animate_loading_dots(0)
    else:
        animation_label.place_forget()

def _animate_loading_dots(dot_count: int):
    """Cycles through '.', '..', '...' on the animation label."""
    if "Searching" not in status_label.cget("text"): # Stop if status changed
        animation_label.place_forget()
        return
    
    num_dots = (dot_count % 3) + 1
    animation_label.config(text='.' * num_dots)
    root.after(500, lambda: _animate_loading_dots(dot_count + 1))

def setup_ui(root):
    """Configures the main window and creates all UI widgets."""
    root.attributes('-fullscreen', True)
    root.config(bg=COLOR_BACKGROUND, cursor="none")

    # Define fonts based on screen size for responsiveness
    screen_height = root.winfo_screenheight()
    title_font_size = max(48, screen_height // 15)
    anim_font_size = max(60, screen_height // 12)
    
    title_font = tkFont.Font(family="Helvetica", size=title_font_size, weight="bold")
    anim_font = tkFont.Font(family="Helvetica", size=anim_font_size, weight="bold")

    # Main status label (e.g., "Searching for Wi-Fi")
    global status_label
    status_label = tk.Label(root, text="Initializing...", font=title_font,
                            fg=COLOR_FOREGROUND, bg=COLOR_BACKGROUND)
    status_label.place(relx=0.5, rely=0.45, anchor='center')

    # Label for the "..." animation
    global animation_label
    animation_label = tk.Label(root, text="", font=anim_font,
                               fg=COLOR_FOREGROUND, bg=COLOR_BACKGROUND)

# ── main execution ───────────────────────────────────────────────────────

if __name__ == '__main__':
    root = tk.Tk()
    setup_ui(root)
    
    log_toast("PixelPaper Frame starting up.", "INIT")

    # Start background services
    threading.Thread(target=start_gatt_server, daemon=True).start()
    disable_pairing()

    # Start the first status check
    root.after(1000, update_status)

    root.mainloop()