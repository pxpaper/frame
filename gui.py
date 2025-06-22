#!/usr/bin/env python3
"""
gui.py – Pixel-Paper frame GUI & BLE provisioning (Optimized)

• Now detects and recovers from "Aw, Snap!" page crashes in Chromium.
• Requires 'xdotool' (install with: sudo apt-get install xdotool).
• Timezone-aware, timetable-based auto-brightness.
• Handles complex BLE commands for all features.
"""

import os, queue, socket, subprocess, threading, time, tkinter as tk, json, sys
from itertools import count
from bluezero import adapter, peripheral
import ttkbootstrap as tb
from ttkbootstrap.toast import ToastNotification
from ttkbootstrap import ttk
from PIL import Image, ImageTk, ImageSequence
from datetime import datetime
import pytz

# ── paths & constants ───────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
TIMEZONE_FILE = os.path.join(SCRIPT_DIR, 'timezone.json')
SPINNER_GIF = os.path.join(SCRIPT_DIR, "loading.gif")
WIFI_ON_ICON  = os.path.join(SCRIPT_DIR, "assets", "wifi_on.png")
WIFI_OFF_ICON = os.path.join(SCRIPT_DIR, "assets", "wifi_off.png")

# ── Timetable ──────────────────────────────────────────────────────────
TIMETABLE = {
    (0, 6): 0, (6, 7): 25, (7, 8): 50, (8, 9): 75,
    (9, 18): 100, (18, 19): 75, (19, 20): 50,
    (20, 21): 25, (21, 24): 0,
}

# ── constants & globals ─────────────────────────────────────────────────
GREEN  = "#1FC742"
GREEN2 = "#025B18"
FAIL_MAX         = 3
chromium_process = None
fail_count       = 0
PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"
SERIAL_CHAR_UUID          = "12345678-1234-5678-1234-56789abcdef2"

toast_queue = queue.SimpleQueue()
wifi_status_queue = queue.SimpleQueue()
auto_brightness_enabled = False
last_set_brightness = -1

# ─────────────────────────── Optimized Toast ─────────────────────────────
def show_toast_from_queue():
    """Processes one toast message from the queue."""
    try:
        if not toast_queue.empty():
            msg, style = toast_queue.get_nowait()
            toast = ToastNotification(
                title="Pixel Paper", message=msg, duration=3000,
                bootstyle=style, position=(10, 10, 'ne'), alpha=0.9
            )
            toast.show_toast()
    finally:
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
    if not os.path.exists(SPINNER_GIF): return
    try:
        with Image.open(SPINNER_GIF) as img:
            spinner_frames = [ImageTk.PhotoImage(frame.copy()) for frame in ImageSequence.Iterator(img)]
    except Exception as e:
        log_message(f"Spinner Error: {e}", "danger")

def animate_spinner(idx=0):
    if not spinner_running or not spinner_frames: return
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
                subprocess.run(["sudo", "nmcli", "c", "delete", uuid], check=False, capture_output=True)
        subprocess.run(["sudo", "nmcli", "c", "reload"], check=False)
    except Exception as exc:
        log_message(f"Wi-Fi Clear Error: {exc}", "warning")

# ── Non-Blocking Wi-Fi & Chromium Management ─────────────────────────────
def wifi_check_worker():
    """Continuously checks Wi-Fi status in a background thread."""
    while True:
        try:
            s = socket.create_connection(("8.8.8.8", 53), timeout=5)
            s.close()
            wifi_status_queue.put(True)
        except OSError:
            wifi_status_queue.put(False)
        time.sleep(5)

def check_chromium_page_health():
    """
    Checks if the active Chromium window's title indicates a crash.
    Returns True if healthy, False if crashed ("Aw, Snap!").
    Requires 'xdotool' to be installed (sudo apt-get install xdotool).
    """
    if chromium_process is None or chromium_process.poll() is not None:
        return True # Not running, so not crashed in this context. The main loop will handle restart.
    try:
        # Get the ID of the active window
        active_window_cmd = ["xdotool", "getactivewindow"]
        active_window_id = subprocess.check_output(active_window_cmd, text=True, timeout=1).strip()

        # Get the name of the active window by its ID
        window_name_cmd = ["xdotool", "getwindowname", active_window_id]
        window_title = subprocess.check_output(window_name_cmd, text=True, timeout=1).strip().lower()

        # Check for common crash-related titles. "untitled" can be a symptom.
        crashed_titles = ["aw, snap!", "untitled"]
        if any(title in window_title for title in crashed_titles):
            log_message(f"Detected 'Aw, Snap!' error. Window title: {window_title}", "warning")
            return False
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
        # If xdotool fails, assume it's okay to avoid false positives.
        # Log the error so the user knows if xdotool is missing.
        print(f"Could not check window title (is xdotool installed?): {e}", flush=True)
        return True

def manage_system_state():
    """Checks queue and updates GUI/Chromium without blocking. Acts as a watchdog."""
    global chromium_process, fail_count
    try:
        is_connected = wifi_status_queue.get_nowait()
        if wifi_on_img and wifi_off_img:
            wifi_icon_label.config(image=wifi_on_img if is_connected else wifi_off_img)

        if is_connected:
            fail_count = 0
            bottom_label.config(text="")
            
            # This is the watchdog logic. It now checks for a full process crash OR an "Aw, Snap!" page crash.
            is_process_dead = chromium_process is None or chromium_process.poll() is not None
            is_page_crashed = not check_chromium_page_health()

            if is_process_dead or is_page_crashed:
                if is_process_dead and chromium_process is not None:
                    log_message("Chromium process not found. Restarting...", "info")
                
                status_label.config(text="Wi-Fi Connected")
                show_spinner()
                subprocess.run(["pkill", "-f", "chromium"], check=False)
                
                url = f"https://pixelpaper.com/frame.html?id={get_serial_number()}"
                
                chromium_flags = [
                    "chromium",
                    "--kiosk",
                    "--no-sandbox",
                    "--disable-extensions",
                    "--autoplay-policy=no-user-gesture-required",
                    url
                ]
                chromium_process = subprocess.Popen(chromium_flags)
        else:
            hide_spinner()
            fail_count += 1
            if fail_count > FAIL_MAX:
                status_label.config(text="Waiting for Wi-Fi…")
    except queue.Empty:
        pass
    except Exception as e:
        log_message(f"State Error: {e}", "danger")

    root.after(1000, manage_system_state)

# ── Timezone and Brightness Logic ───────────────────────────────
def get_current_timezone():
    try:
        if os.path.exists(TIMEZONE_FILE):
            with open(TIMEZONE_FILE, 'r') as f:
                data = json.load(f)
                return pytz.timezone(data.get('timezone', 'UTC'))
    except Exception:
        pass
    return pytz.timezone('UTC')

def set_manual_brightness(value, silent=False):
    """Sets a specific brightness, caches it, and optionally logs."""
    global last_set_brightness
    if value == last_set_brightness:
        return
    try:
        subprocess.run(["ddcutil", "setvcp", "10", str(value)], check=True)
        if not silent:
            log_message(f"Brightness set to {value}%")
        last_set_brightness = value
    except Exception as e:
        log_message(f"Brightness command failed: {e}", "danger")

def set_brightness_for_time():
    """Apply brightness from TIMETABLE using saved timezone."""
    tz = get_current_timezone()
    current_hour = datetime.now(tz).hour
    for (start, end), lvl in TIMETABLE.items():
        if start <= current_hour < end:
            set_manual_brightness(lvl, silent=True)
            return

def auto_brightness_worker():
    while True:
        if auto_brightness_enabled:
            set_brightness_for_time()
        time.sleep(300)

def timed_chromium_restart_worker():
    """Restarts Chromium every 12 hours to keep it fresh."""
    global chromium_process
    restart_interval = 12 * 60 * 60
    while True:
        time.sleep(restart_interval)
        log_message("Performing scheduled 12-hour Chromium restart.", "info")
        if chromium_process and chromium_process.poll() is None:
            try:
                chromium_process.kill()
            except Exception:
                subprocess.run(["pkill", "-f", "chromium"], check=False)
        chromium_process = None

# ─────────────────── BLE provisioning handlers ────────────────────────
def check_wifi_connection():
    try:
        s = socket.create_connection(("8.8.8.8", 53), timeout=3)
        s.close(); return True
    except OSError:
        return False
        
def handle_wifi_data(payload: str):
    global fail_count
    try:
        ssid_part, pass_part = payload.split(';', 1)
        if pass_part.upper().startswith("PASS:"):
            password = pass_part[5:]
        else:
            password = pass_part
        ssid = ssid_part
    except ValueError:
        log_message(f"Invalid WIFI format: {payload}", "danger")
        return

    if not ssid or not password:
        log_message("SSID or Password is empty after parsing.", "warning")
        return

    log_message(f"Configuring Wi-Fi for '{ssid}'...")
    show_spinner()
    
    interface_name = "wlan0"
    
    try:
        subprocess.run(
            ["sudo", "nmcli", "connection", "delete", ssid],
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

        add_command = [
            "sudo", "nmcli", "connection", "add", "type", "wifi",
            "con-name", ssid, "ifname", interface_name, "ssid", ssid,
            "--", "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password
        ]
        subprocess.run(add_command, check=True, capture_output=True, text=True)
        
        up_command = ["sudo", "nmcli", "connection", "up", ssid]
        subprocess.run(up_command, check=True, capture_output=True, text=True)

    except subprocess.CalledProcessError as e:
        hide_spinner()
        log_message("Connection failed. Please check credentials.", "danger")
        print(f"[nmcli error] STDERR: {e.stderr}")
        bottom_label.config(text="Authentication failed")
        status_label.config(text="Waiting for Wi-Fi…")
        fail_count = -999
        return

    def verdict():
        if check_wifi_connection():
            log_message(f"Successfully connected to '{ssid}'", "success")
            bottom_label.config(text="")
        else:
            hide_spinner()
            log_message("Failed to get internet. Check network.", "warning")
            bottom_label.config(text="No internet")
            status_label.config(text="Waiting for Wi-Fi…")
            fail_count = -999
            
    root.after(8000, verdict)

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

def handle_clear_wifi():
    global chromium_process, fail_count
    if chromium_process:
        chromium_process.kill()
        chromium_process = None
    clear_wifi_profiles()
    hide_spinner()
    bottom_label.config(text="")
    status_label.config(text="Waiting for Wi-Fi…")
    while not wifi_status_queue.empty():
        try:
            wifi_status_queue.get_nowait()
        except queue.Empty:
            break
    if wifi_off_img:
        wifi_icon_label.config(image=wifi_off_img)

def ble_callback(val, _):
    global auto_brightness_enabled
    if val is None: return
    msg = (bytes(val) if isinstance(val, list) else val).decode("utf-8", "ignore").strip()
    
    print(f"Received BLE command: {msg}")

    if msg.startswith("WIFI:"):
        handle_wifi_data(msg[5:])
    elif msg.startswith("ORIENT:"):
        handle_orientation_change(msg[7:])
    elif msg.startswith("TIMEZONE:"):
        tz_name = msg[9:]
        try:
            pytz.timezone(tz_name)
            with open(TIMEZONE_FILE, 'w') as f:
                json.dump({'timezone': tz_name}, f)
            print(f"Timezone set to {tz_name}")
        except Exception:
            print(f"ERROR: Invalid timezone received: {tz_name}")

    elif msg.startswith("BRIGHT:"):
        if auto_brightness_enabled:
            auto_brightness_enabled = False
            log_message("Auto-brightness disabled.")
        try:
            set_manual_brightness(int(msg[7:]))
        except ValueError:
            log_message(f"Invalid brightness value: {msg[7:]}", "warning")

    elif msg.startswith("AUTOBRIGHT:"):
        value = msg[11:]
        if value.startswith("ON"):
            auto_brightness_enabled = True
            set_brightness_for_time()
            log_message("Auto-brightness enabled")
        elif value.startswith("OFF"):
            auto_brightness_enabled = False
            try:
                snap = int(value.split(':',1)[1])
                set_manual_brightness(snap, silent=True)
                log_message(f"Auto-brightness OFF. Set to {snap}%")
            except Exception:
                log_message("Auto-brightness disabled")

    elif msg == "CLEAR_WIFI":
        handle_clear_wifi()
    elif msg == "REBOOT":
        subprocess.run(["sudo", "reboot"], check=False)
    else:
        log_message(f"Unknown BLE cmd: {msg}", "warning")

def start_gatt():
    """Initializes and runs the BLE GATT server in a persistent loop."""
    while True:
        try:
            dongles = adapter.Adapter.available()
            if not dongles:
                log_message("No BLE adapter found!", "danger")
                time.sleep(5)
                continue
            
            addr = list(dongles)[0].address
            ble = peripheral.Peripheral(addr, local_name="PixelPaper")
            
            ble.add_service(1, PROVISIONING_SERVICE_UUID, primary=True)
            ble.add_characteristic(1, 1, PROVISIONING_CHAR_UUID,
                                   [], False, ['write', 'write-without-response'],
                                   write_callback=ble_callback)
            ble.add_characteristic(1, 2, SERIAL_CHAR_UUID,
                                   list(get_serial_number().encode()), False, ['read'],
                                   read_callback=lambda _o: list(get_serial_number().encode()))
            
            ble.publish()
        except Exception as e:
            log_message(f"GATT error: {e}", "danger")
            time.sleep(5)

# ─────────────────────────── Build GUI ────────────────────────────────
root = tb.Window(themename="darkly")
root.config(cursor="none")

def _show_then_hide(_):
    root.config(cursor="arrow")
    if hasattr(_show_then_hide, "job"): root.after_cancel(_show_then_hide.job)
    _show_then_hide.job = root.after(500, lambda: root.config(cursor="none"))

root.bind("<Motion>", _show_then_hide)
root.style.colors.set('info', GREEN)
root.style.configure("TFrame", background="black")
root.style.configure("Status.TLabel", background="black", foreground=GREEN, font=("Helvetica", 48, "bold"))
root.style.configure("Secondary.TLabel", background="black", foreground=GREEN2, font=("Helvetica", 24))
root.configure(bg="black")
root.title("Frame Status")
root.attributes("-fullscreen", True)
root.bind("<Escape>", lambda e: root.attributes("-fullscreen", False))

wifi_on_img = wifi_off_img = None
try:
    icon_size = (90, 90)
    resample_filter = Image.Resampling.LANCZOS if hasattr(Image, 'Resampling') else Image.LANCZOS
    def process_icon(filepath):
        if not os.path.exists(filepath): return None
        with Image.open(filepath) as img:
            img_rgba = img.convert("RGBA")
            resized_icon = img_rgba.resize(icon_size, resample_filter)
            background = Image.new("RGBA", icon_size, (0, 0, 0, 255))
            background.paste(resized_icon, (0, 0), resized_icon)
            return ImageTk.PhotoImage(background)
    wifi_on_img = process_icon(WIFI_ON_ICON)
    wifi_off_img = process_icon(WIFI_OFF_ICON)
except Exception as e:
    log_message(f"Icon load error: {e}", "danger")

wifi_icon_label = tk.Label(root, bg="black", bd=0, highlightthickness=0)
if wifi_off_img: wifi_icon_label.config(image=wifi_off_img)
wifi_icon_label.place(x=10, y=10)

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
threading.Thread(target=auto_brightness_worker, daemon=True).start()
threading.Thread(target=timed_chromium_restart_worker, daemon=True).start()
root.after(100, show_toast_from_queue)
root.after(1000, manage_system_state)

root.mainloop()
