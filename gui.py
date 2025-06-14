#!/usr/bin/env python3
"""
gui.py – Pixel-Paper frame GUI & BLE provisioning

• Animated loading.gif spinner (2× speed) while Chromium launches
• BLE commands: WIFI, ORIENT, CLEAR_WIFI, REBOOT
• On wrong Wi-Fi password, shows ‘Authentication failed — wrong password?’
  in a persistent bottom line until another Wi-Fi attempt succeeds.
"""

import os, queue, socket, subprocess, threading, time, tkinter as tk
from itertools import count
from bluezero import adapter, peripheral
import ttkbootstrap as tb
from ttkbootstrap.toast import ToastNotification
from ttkbootstrap import ttk

# ── paths ───────────────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
SPINNER_GIF = os.path.join(SCRIPT_DIR, "loading.gif")   # provide your GIF here

# ── constants & globals ─────────────────────────────────────────────────
GREEN  = "#1FC742"
GREEN2 = "#025B18"
FAIL_MAX          = 3
chromium_process  = None
fail_count        = 0

PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"
SERIAL_CHAR_UUID          = "12345678-1234-5678-1234-56789abcdef2"

toast_queue, _toast_on_screen = queue.SimpleQueue(), False

# ─────────────────────────── Toast helpers ─────────────────────────────
def _show_next_toast():
    global _toast_on_screen
    if _toast_on_screen or toast_queue.empty():
        return
    _toast_on_screen = True
    msg = toast_queue.get()

    class SmoothToast(ToastNotification):
        def hide_toast(self, *_):
            try:
                alpha = float(self.toplevel.attributes("-alpha"))
                if alpha <= 0.02:
                    self.toplevel.destroy(); _finish()
                else:
                    self.toplevel.attributes("-alpha", alpha - 0.02)
                    self.toplevel.after(25, self.hide_toast)
            except Exception:
                self.toplevel.destroy(); _finish()

    def _finish():
        global _toast_on_screen
        _toast_on_screen = False
        root.after_idle(_show_next_toast)

    SmoothToast(master=root, title="Pixel Paper", message=msg,
                bootstyle="info", duration=3000,
                position=(10, 10, "ne"), alpha=0.95).show_toast()

def log_debug(msg: str):
    """Queue a toast and ensure the toast pump is running."""
    toast_queue.put(msg)
    try:
        root.after_idle(_show_next_toast)
    except NameError:
        pass
    print(msg, flush=True)

# ───────────────────────── Spinner helpers ─────────────────────────────
spinner_frames, spinner_running = [], False
SPIN_DELAY = 40  # ms (≈2× normal speed)

def load_spinner():
    if not os.path.exists(SPINNER_GIF):
        return
    for i in count():
        try:
            spinner_frames.append(
                tk.PhotoImage(file=SPINNER_GIF, format=f"gif -index {i}"))
        except tk.TclError:
            break

def animate_spinner(idx=0):
    if not spinner_running or not spinner_frames:
        return
    spinner_label.configure(image=spinner_frames[idx])
    root.after(SPIN_DELAY, animate_spinner, (idx + 1) % len(spinner_frames))

def show_spinner():
    global spinner_running
    if spinner_running or not spinner_frames:
        return
    spinner_label.pack(pady=(12, 0))
    spinner_running = True
    animate_spinner()

def hide_spinner():
    global spinner_running
    if not spinner_running:
        return
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
    subprocess.run(["bluetoothctl"], input="pairable no\nquit\n",
                   text=True, capture_output=True)

def check_wifi_connection():
    try:
        s = socket.create_connection(("8.8.8.8", 53), timeout=3)
        s.close(); return True
    except OSError:
        return False

def clear_wifi_profiles():
    try:
        out = subprocess.check_output(
            ["nmcli", "-t", "-f", "UUID,TYPE", "connection", "show"],
            text=True)
        for ln in out.splitlines():
            uuid, ctype = ln.split(':', 1)
            if ctype == "802-11-wireless":
                subprocess.run(["nmcli", "connection", "delete", uuid],
                               check=False, capture_output=True)
        subprocess.run(["nmcli", "connection", "reload"], check=False)
    except Exception as exc:
        log_debug(f"clear_wifi_profiles: {exc}")

# ─────────────────── Wi-Fi & Chromium poll loop ───────────────────────
def update_status():
    global chromium_process, fail_count
    try:
        if check_wifi_connection():
            fail_count = 0
            bottom_label.config(text="")  # clear any auth-fail msg
            if chromium_process is None or chromium_process.poll() is not None:
                status_label.config(text="Wi-Fi Connected")
                show_spinner()
                subprocess.run(["pkill", "-f", "chromium"], check=False)
                url = f"https://pixelpaper.com/frame.html?id={get_serial_number()}"
                chromium_process = subprocess.Popen(["chromium", "--kiosk", url])
        else:
            hide_spinner()
            fail_count += 1
            if fail_count > FAIL_MAX:
                status_label.config(text="Waiting for Wi-Fi…")
    except Exception as e:
        log_debug(f"update_status: {e}")

    root.after(5000, update_status)

# ─────────────────── BLE provisioning handlers ────────────────────────
def handle_wifi_data(payload: str):
    """Try supplied SSID/password. Show auth failure on bottom line."""
    global fail_count
    try:
        ssid, password = payload.split(';', 1)[0], payload.split(':', 1)[1]
    except ValueError:
        log_debug("Wi-Fi payload malformed"); return

    clear_wifi_profiles()
    subprocess.run([
        "nmcli", "connection", "add",
        "type", "wifi", "ifname", "wlan0",
        "con-name", ssid, "ssid", ssid,
        "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password,
        "802-11-wireless-security.psk-flags", "0",
        "connection.autoconnect", "yes"
    ], check=False)

    def verdict():
        nonlocal ssid
        if check_wifi_connection():
            log_debug(f"Connected to: '{ssid}'")
            bottom_label.config(text="")
        else:
            subprocess.run(["nmcli", "connection", "delete", ssid], check=False)
            hide_spinner()
            bottom_label.config(text="Authentication failed — wrong password?")
            status_label.config(text="Waiting for Wi-Fi…")
            fail_count = -999  # keep bottom msg until next attempt

    root.after(6000, verdict)  # allow WPA handshake

def handle_orientation_change(arg: str):
    """Rotate HDMI output via kanshi (normal|90|180|270)."""
    output = "HDMI-A-1"
    try:
        mode = subprocess.check_output(
            "wlr-randr | grep '(current)' | awk '{print $1\"@\"$3}'",
            shell=True, text=True).strip()
    except subprocess.CalledProcessError as e:
        log_debug(f"Detect mode failed: {e}"); return
    cfg = f"profile {{\n    output {output} enable mode {mode} position 0,0 transform {arg}\n}}\n"
    p = os.path.expanduser("~/.config/kanshi/config")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f: f.write(cfg)
    os.chmod(p, 0o600)
    subprocess.run(["killall", "kanshi"], check=False)
    subprocess.Popen(["kanshi", "-c", p],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log_debug("Portrait" if arg in ("90", "270") else "Landscape")

def ble_callback(val, _):
    if val is None: return
    msg = (bytes(val) if isinstance(val, list) else val).decode("utf-8", "ignore").strip()
    if   msg.startswith("WIFI:"):   handle_wifi_data(msg[5:])
    elif msg.startswith("ORIENT:"): handle_orientation_change(msg[7:])
    # --- START: Added brightness control ---
    elif msg.startswith("BRIGHT:"):
        try:
            brightness_value = int(msg[7:])
            if 0 <= brightness_value <= 100:
                subprocess.run(["ddcutil", "set", "10", str(brightness_value)], check=True)
                log_debug(f"Brightness set to {brightness_value}%")
            else:
                log_debug("Brightness value out of range (0-100)")
        except (ValueError, subprocess.CalledProcessError) as e:
            log_debug(f"Brightness command failed: {e}")
    # --- END: Added brightness control ---
    elif msg == "CLEAR_WIFI":       clear_wifi_profiles(); hide_spinner(); bottom_label.config(text=""); status_label.config(text="Waiting for Wi-Fi…"); subprocess.run(["pkill","-f","chromium"], check=False)
    elif msg == "REBOOT":           subprocess.run(["sudo", "reboot"], check=False)
    else: log_debug(f"Unknown BLE cmd: {msg}")

# ───────────────────────── BLE server thread ──────────────────────────
def start_gatt():
    while True:
        try:
            dongles = adapter.Adapter.available()
            if not dongles: log_debug("No BLE adapter!"); time.sleep(5); continue
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
        except Exception as e: log_debug(f"GATT error: {e}")
        time.sleep(5)

# ─────────────────────────── Build GUI ────────────────────────────────
root = tb.Window(themename="litera")

root.config(cursor="none")

def _show_then_hide(_):
    root.config(cursor="arrow")
    if hasattr(_show_then_hide, "job"):
        root.after_cancel(_show_then_hide.job)
    _show_then_hide.job = root.after(500,
                                     lambda: root.config(cursor="none"))

root.bind("<Motion>", _show_then_hide)

root.style.colors.set("info", GREEN)
root.style.configure("TFrame", background="black")
root.style.configure("Status.TLabel", background="black",
                     foreground=GREEN, font=("Helvetica", 48))
root.style.configure("Secondary.TLabel", background="black",
                     foreground=GREEN2, font=("Helvetica", 24))

root.configure(bg="black")
root.title("Frame Status")
root.attributes("-fullscreen", True)
root.bind("<Escape>", lambda e: root.attributes("-fullscreen", False))
root.after_idle(_show_next_toast)

center = ttk.Frame(root, style="TFrame"); center.pack(expand=True)
status_label = ttk.Label(center, text="Checking Wi-Fi…", style="Status.TLabel")
status_label.pack()

load_spinner()
spinner_label = tk.Label(center, bg="black", bd=0, highlightthickness=0)

bottom_label = ttk.Label(root, text="", style="Secondary.TLabel")
bottom_label.pack(side="bottom", pady=10)

disable_pairing()
threading.Thread(target=start_gatt, daemon=True).start()
update_status()

root.mainloop()