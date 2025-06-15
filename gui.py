#!/usr/bin/env python3
"""
gui.py – Pixel-Paper frame GUI & BLE provisioning (Optimized)

• Non-blocking Wi-Fi check for a responsive UI.
• Smoother, artifact-free toast notifications.
• Efficient GIF handling with Pillow.
• BLE commands: WIFI, ORIENT, BRIGHT, CLEAR_WIFI, REBOOT
"""

import os, queue, socket, subprocess, threading, time, tkinter as tk
from itertools import count
from bluezero import adapter, peripheral
import ttkbootstrap as tb
from ttkbootstrap.toast import ToastNotification
from ttkbootstrap import ttk
from PIL import Image, ImageTk, ImageSequence # <-- NEW: For optimized GIF handling

# ── paths ───────────────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
SPINNER_GIF = os.path.join(SCRIPT_DIR, "loading.gif")

# ── constants & globals ─────────────────────────────────────────────────
GREEN  = "#1FC742"
GREEN2 = "#025B18"
FAIL_MAX          = 3
chromium_process  = None
fail_count        = 0

PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"
SERIAL_CHAR_UUID          = "12345678-1234-5678-1234-56789abcdef2"

toast_queue = queue.SimpleQueue()
wifi_status_queue = queue.SimpleQueue()

# ─────────────────────────── Optimized Toast ─────────────────────────────
def show_toast_from_queue():
    """Processes one toast message from the queue."""
    try:
        if not toast_queue.empty():
            msg, style = toast_queue.get_nowait()
            toast = ToastNotification(
                title="Pixel Paper",
                message=msg,
                duration=3000,
                bootstyle=style,
                position=(10, 10, 'ne'),
                alpha=0.9
            )
            toast.show_toast()
    finally:
        # Always check for the next message after a delay
        root.after(100, show_toast_from_queue)

def log_message(msg: str, style="info"):
    """Public function to queue a toast message."""
    toast_queue.put((msg, style))
    print(msg, flush=True)

# ─────────────────── Optimized Spinner with Pillow ─────────────────────
spinner_frames, spinner_running = [], False
SPIN_DELAY = 40

def load_spinner():
    """Loads GIF frames using Pillow for better performance."""
    global spinner_frames
    if not os.path.exists(SPINNER_GIF):
        return
    try:
        with Image.open(SPINNER_GIF) as img:
            spinner_frames = [ImageTk.PhotoImage(frame.copy()) for frame in ImageSequence.Iterator(img)]
    except Exception as e:
        log_message(f"Spinner Error: {e}", "danger")

def animate_spinner(idx=0):
    if not spinner_running or not spinner_frames:
        return
    spinner_label.config(image=spinner_frames[idx])
    root.after(SPIN_DELAY, animate_spinner, (idx + 1) % len(spinner_frames))

def show_spinner():
    global spinner_running
    if spinner_running or not spinner_frames: return
    spinner_label.pack(pady=(12, 0))
    spinner_running = True
    animate_spinner()

def hide_spinner():
    global spinner_running
    if not spinner_running: return
    spinner_label.pack_forget()
    spinner_running = False

# ───────────────────────── Utility helpers ─────────────────────────────
def get_serial_number():
    try:
        with open('/proc/device-tree/serial-number') as f:
            return "PX" + f.read().strip('\x00\n ')
    except Exception:
        return "PXunknown"

def disable_pairing():
    subprocess.run(["bluetoothctl"], input="pairable no\nquit\n", text=True, capture_output=True)

def clear_wifi_profiles():
    try:
        out = subprocess.check_output(["nmcli", "-t", "-f", "UUID,TYPE", "c"], text=True)
        for ln in out.splitlines():
            uuid, ctype = ln.split(':', 1)
            if ctype == "802-11-wireless":
                subprocess.run(["nmcli", "c", "delete", uuid], check=False, capture_output=True)
        subprocess.run(["nmcli", "c", "reload"], check=False)
    except Exception as exc:
        log_message(f"Wi-Fi Clear Error: {exc}", "warning")

# ── NEW: Non-Blocking Wi-Fi & Chromium Management ──────────────────────
def wifi_check_worker():
    """Continuously checks Wi-Fi status in a background thread."""
    while True:
        try:
            s = socket.create_connection(("8.8.8.8", 53), timeout=5)
            s.close()
            wifi_status_queue.put(True)
        except OSError:
            wifi_status_queue.put(False)
        time.sleep(5) # Check every 5 seconds

def manage_system_state():
    """Checks queue and updates GUI/Chromium without blocking."""
    global chromium_process, fail_count
    try:
        is_connected = wifi_status_queue.get_nowait()
        if is_connected:
            fail_count = 0
            bottom_label.config(text="")
            if chromium_process is None or chromium_process.poll() is not None:
                status_label.config(text="Wi-Fi Connected")
                show_spinner()
                subprocess.run(["pkill", "-f", "chromium"], check=False)
                url = f"https://pixelpaper.com/frame.html?id={get_serial_number()}"
                chromium_process = subprocess.Popen(["chromium", "--kiosk", "--disable-features=Translate", url])
        else:
            hide_spinner()
            fail_count += 1
            if fail_count > FAIL_MAX:
                status_label.config(text="Waiting for Wi-Fi…")
    except queue.Empty:
        pass # No new status, just wait for the next check
    except Exception as e:
        log_message(f"State Error: {e}", "danger")

    root.after(1000, manage_system_state) # Check queue every second


# ─────────────────── BLE provisioning handlers (UNCHANGED) ──────────────
def handle_wifi_data(payload: str):
    global fail_count
    try:
        ssid, password = payload.split(';', 1)[0], payload.split(':', 1)[1]
    except ValueError:
        log_message("Wi-Fi payload malformed", "warning"); return

    clear_wifi_profiles()
    subprocess.run(["nmcli", "d", "wifi", "connect", ssid, "password", password], check=False)

    def verdict():
        # Force an immediate check instead of waiting for the worker
        if check_wifi_connection():
            log_message(f"Connected to: '{ssid}'")
            bottom_label.config(text="")
        else:
            subprocess.run(["nmcli", "c", "delete", ssid], check=False)
            hide_spinner()
            bottom_label.config(text="Authentication failed — wrong password?")
            status_label.config(text="Waiting for Wi-Fi…")
            fail_count = -999

    root.after(6000, verdict)

def handle_orientation_change(arg: str):
    output = "HDMI-A-1"
    try:
        mode = subprocess.check_output("wlr-randr | grep '(current)' | awk '{print $1\"@\"$3}'", shell=True, text=True).strip()
    except subprocess.CalledProcessError as e:
        log_message(f"Detect mode failed: {e}", "warning"); return
    cfg = f"profile {{\n    output {output} enable mode {mode} position 0,0 transform {arg}\n}}\n"
    p = os.path.expanduser("~/.config/kanshi/config")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f: f.write(cfg)
    os.chmod(p, 0o600)
    subprocess.run(["killall", "kanshi"], check=False)
    subprocess.Popen(["kanshi", "-c", p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log_message("Portrait" if arg in ("90", "270") else "Landscape")

def ble_callback(val, _):
    if val is None: return
    msg = (bytes(val) if isinstance(val, list) else val).decode("utf-8", "ignore").strip()
    if   msg.startswith("WIFI:"):   handle_wifi_data(msg[5:])
    elif msg.startswith("ORIENT:"): handle_orientation_change(msg[7:])
    elif msg.startswith("BRIGHT:"):
        try:
            brightness_value = int(msg[7:])
            if 0 <= brightness_value <= 100:
                subprocess.run(["ddcutil", "set", "10", str(brightness_value)], check=True)
                log_message(f"Brightness: {brightness_value}%")
            else:
                log_message("Brightness value out of range (0-100)", "warning")
        except (ValueError, subprocess.CalledProcessError) as e:
            log_message(f"Brightness command failed: {e}", "danger")
    elif msg == "CLEAR_WIFI":
        clear_wifi_profiles(); hide_spinner()
        bottom_label.config(text=""); status_label.config(text="Waiting for Wi-Fi…")
        subprocess.run(["pkill","-f","chromium"], check=False)
    elif msg == "REBOOT":
        subprocess.run(["sudo", "reboot"], check=False)
    else:
        log_message(f"Unknown BLE cmd: {msg}", "warning")

# ───────────────────────── BLE server thread (UNCHANGED) ────────────────
def start_gatt():
    while True:
        try:
            dongles = adapter.Adapter.available()
            if not dongles: log_message("No BLE adapter!", "danger"); time.sleep(5); continue
            addr = list(dongles)[0].address
            ble  = peripheral.Peripheral(addr, local_name="PixelPaper")
            ble.add_service(1, PROVISIONING_SERVICE_UUID, primary=True)
            ble.add_characteristic(1, 1, PROVISIONING_CHAR_UUID,
                                   value=[], notifying=False,
                                   flags=['write', 'write-without-response'],
                                   write_callback=ble_callback)
            ble.add_characteristic(1, 2, SERIAL_CHAR_UUID,
                                   value=list(get_serial_number().encode()),
                                   notifying=False, flags=['read'],
                                   read_callback=lambda _o: list(get_serial_number().encode()))
            ble.publish()
        except Exception as e: log_message(f"GATT error: {e}", "danger")
        time.sleep(5)

# ─────────────────────────── Build GUI ────────────────────────────────
root = tb.Window(themename="darkly") # A darker, modern theme
root.config(cursor="none")

def _show_then_hide(_):
    root.config(cursor="arrow")
    if hasattr(_show_then_hide, "job"): root.after_cancel(_show_then_hide.job)
    _show_then_hide.job = root.after(500, lambda: root.config(cursor="none"))

root.bind("<Motion>", _show_then_hide)

root.style.configure("TFrame", background="black")
root.style.configure("Status.TLabel", background="black", foreground=GREEN, font=("Helvetica", 48, "bold"))
root.style.configure("Secondary.TLabel", background="black", foreground=GREEN2, font=("Helvetica", 24))

root.configure(bg="black")
root.title("Frame Status")
root.attributes("-fullscreen", True)
root.bind("<Escape>", lambda e: root.attributes("-fullscreen", False))

center = ttk.Frame(root, style="TFrame"); center.pack(expand=True)
status_label = ttk.Label(center, text="Checking Wi-Fi…", style="Status.TLabel")
status_label.pack()

load_spinner()
spinner_label = tk.Label(center, bg="black", bd=0, highlightthickness=0)

bottom_label = ttk.Label(root, text="", style="Secondary.TLabel")
bottom_label.pack(side="bottom", pady=10)

disable_pairing()
threading.Thread(target=start_gatt, daemon=True).start()
threading.Thread(target=wifi_check_worker, daemon=True).start()
root.after(1000, manage_system_state)
root.after(100, show_toast_from_queue)

root.mainloop()
