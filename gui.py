#!/usr/bin/env python3
"""
gui.py – Frame GUI & BLE provisioning for Pixel Paper
Adds centred loading.gif spinner (2× speed) while Chromium launches,
plus BLE command  CLEAR_WIFI  to wipe every stored Wi-Fi profile.
"""
import os, queue, socket, subprocess, threading, time, tkinter as tk
from itertools import count
from bluezero import adapter, peripheral
import ttkbootstrap as tb
from ttkbootstrap.toast import ToastNotification
from ttkbootstrap import ttk

# ── paths ──────────────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
SPINNER_GIF = os.path.join(SCRIPT_DIR, "loading.gif")   # put loading.gif here

# ── constants / globals ────────────────────────────────────────────────
GREEN = "#1FC742"
FAIL_MAX          = 3
chromium_process  = None
fail_count        = 0
provisioning_char = None

PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"
SERIAL_CHAR_UUID          = "12345678-1234-5678-1234-56789abcdef2"
STATUS_CHAR_UUID          = "12345678-1234-5678-1234-56789abcdef3"
status_char               = None

toast_queue      = queue.SimpleQueue()
_toast_on_screen = False

# ─────────────────────────── Toast helpers ────────────────────────────
def _show_next_toast():
    global _toast_on_screen
    if _toast_on_screen or toast_queue.empty():
        return
    _toast_on_screen = True
    msg = toast_queue.get()

    class SmoothToast(ToastNotification):
        def hide_toast(self, *_):
            try:
                a = float(self.toplevel.attributes("-alpha"))
                if a <= 0.02:
                    self.toplevel.destroy(); _finish()
                else:
                    self.toplevel.attributes("-alpha", a - 0.02)
                    self.toplevel.after(25, self.hide_toast)
            except Exception:
                self.toplevel.destroy(); _finish()

    def _finish():
        global _toast_on_screen
        _toast_on_screen = False
        root.after_idle(_show_next_toast)

    SmoothToast(title="Pixel Paper", message=msg,
                bootstyle="info", duration=3000,
                position=(10, 10, "ne"), alpha=0.95).show_toast()

def log_debug(m):
    toast_queue.put(m)
    print(m, flush=True)

# ───────────────────────── Spinner helpers ─────────────────────────────
spinner_frames, spinner_running = [], False
SPIN_DELAY = 40   # ms per frame → twice normal speed

def load_spinner():
    if not os.path.exists(SPINNER_GIF):
        return
    for i in count():
        try:
            spinner_frames.append(
                tk.PhotoImage(file=SPINNER_GIF, format=f"gif -index {i}")
            )
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

# ───────────────────────── Utility functions ───────────────────────────
def get_serial_number() -> str:
    try:
        with open('/proc/device-tree/serial-number') as f:
            return "PX" + f.read().strip('\x00\n ')
    except Exception:
        return "PXunknown"

def disable_pairing():
    try:
        subprocess.run(["bluetoothctl"],
                       input="pairable no\nquit\n",
                       text=True, capture_output=True, check=True)
    except Exception as e:
        log_debug(f"Disable pairing failed: {e}")

def check_wifi_connection(retries=2) -> bool:
    for _ in range(retries):
        try:
            s = socket.create_connection(("8.8.8.8", 53), timeout=3)
            s.close(); return True
        except OSError:
            time.sleep(0.3)
    return False

def clear_wifi_profiles():
    """Delete every saved Wi-Fi profile and reload NM."""
    try:
        profiles = subprocess.check_output(
            ["nmcli", "-t", "-f", "UUID,TYPE", "connection", "show"],
            text=True).splitlines()
        for line in profiles:
            uuid, ctype = line.split(':', 1)
            if ctype == "802-11-wireless":
                subprocess.run(["nmcli", "connection", "delete", uuid],
                               check=False, capture_output=True, text=True)
        subprocess.run(["nmcli", "connection", "reload"], check=True)
        subprocess.run(["nmcli", "networking", "off"], check=False)
        subprocess.run(["nmcli", "networking", "on"], check=False)
        log_debug("Wi-Fi profiles cleared")
    except Exception as e:
        log_debug(f"clear_wifi_profiles: {e}")

# ───────────────────── Wi-Fi & Chromium status loop ────────────────────
def update_status():
    global chromium_process, fail_count
    try:
        if check_wifi_connection():
            fail_count = 0
            if chromium_process is None or chromium_process.poll() is not None:
                status_label.configure(text="Wi-Fi Connected")
                show_spinner()
                subprocess.run(["pkill", "-f", "chromium"], check=False)
                url = f"https://pixelpaper.com/frame.html?id={get_serial_number()}"
                chromium_process = subprocess.Popen(["chromium", "--kiosk", url])
        else:
            fail_count += 1
            hide_spinner()
            if fail_count > FAIL_MAX:
                status_label.configure(text="Waiting for Wi-Fi…")
    except Exception as e:
        log_debug(f"update_status: {e}")

    root.after(5000, update_status)

# ──────────────────── BLE callbacks & helpers ──────────────────────────
def handle_wifi_data(data: str):
    try:
        ssid, pass_part = data.split(';', 1)
        password = pass_part.split(':', 1)[1]
    except ValueError:
        log_debug("Wi-Fi payload malformed; expected SSID;PASS:pwd")
        return

    clear_wifi_profiles()

    # 1. add the profile
    subprocess.run([
        "nmcli", "connection", "add",
        "type", "wifi", "ifname", "wlan0",
        "con-name", ssid, "ssid", ssid,
        "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password,
        "802-11-wireless-security.psk-flags", "0",
        "connection.autoconnect", "yes"
    ], check=False)

    # 2. bring it up (don’t fail on non-zero yet)
    subprocess.run(["nmcli", "connection", "up", ssid],
                   capture_output=True, text=True)

    # 3. give NetworkManager a few seconds to finish auth/DHCP
    def final_verdict():
        if check_wifi_connection():
            log_debug(f"Connected to: '{ssid}'")
            send_status("OK")
        else:
            subprocess.run(["nmcli", "connection", "delete", ssid], check=False)
            hide_spinner()
            status_label.configure(text="Wi-Fi authentication failed")
            send_status("AUTH_FAIL")
            root.after(6000, lambda: status_label.configure(text="Waiting for Wi-Fi…"))

    root.after(6000, final_verdict)   # ← 6-second delay


def handle_orientation_change(data: str):
    """Rotate HDMI output via kanshi (data = normal|90|180|270)."""
    output = "HDMI-A-1"
    try:
        mode = subprocess.check_output(
            "wlr-randr | grep '(current)' | awk '{print $1\"@\"$3}'",
            shell=True, text=True).strip()
    except subprocess.CalledProcessError as e:
        log_debug(f"Detect mode failed: {e}")
        return
    cfg = f"profile {{\n    output {output} enable mode {mode} position 0,0 transform {data}\n}}\n"
    path = os.path.expanduser("~/.config/kanshi/config")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f: f.write(cfg)
    os.chmod(path, 0o600)
    subprocess.run(["killall", "kanshi"], check=False)
    subprocess.Popen(["kanshi", "-c", path],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log_debug("Portrait" if data in ("90", "270") else "Landscape")

def ble_callback(value, _options):
    try:
        if value is None: return
        msg = (bytes(value) if isinstance(value, list) else value).decode("utf-8", "ignore").strip()
        if   msg.startswith("WIFI:"):   handle_wifi_data(msg[5:].strip())
        elif msg.startswith("ORIENT:"): handle_orientation_change(msg[7:].strip())
        elif msg == "CLEAR_WIFI":       clear_wifi_profiles(); hide_spinner(); status_label.configure(text="Waiting for Wi-Fi…"); subprocess.run(["pkill","-f","chromium"],check=False)
        elif msg == "REBOOT":           log_debug("Restarting…"); subprocess.run(["sudo","reboot"],check=False)
        else: log_debug("Unknown BLE cmd")
    except Exception as e: log_debug(f"ble_callback: {e}")

def send_status(txt: str):
    if status_char:
        status_char.set_value(list(txt.encode()))
        status_char.notify()

# ───────────────────────── BLE server thread ───────────────────────────
def start_gatt_server():
    global provisioning_char, status_char
    while True:
        try:
            dongles = adapter.Adapter.available()
            if not dongles:
                log_debug("No Bluetooth adapters available!"); time.sleep(5); continue
            addr = list(dongles)[0].address
            ble = peripheral.Peripheral(addr, local_name="PixelPaper")
            ble.add_service(1, PROVISIONING_SERVICE_UUID, primary=True)
            provisioning_char = ble.add_characteristic(
                1, 1, PROVISIONING_CHAR_UUID, value=[], notifying=False,
                flags=['write','write-without-response'], write_callback=ble_callback)
            ble.add_characteristic(
                1, 2, SERIAL_CHAR_UUID,
                value=list(get_serial_number().encode()),
                notifying=False, flags=['read'],
                read_callback=lambda _opt: list(get_serial_number().encode()))
            status_char = ble.add_characteristic(
                1, 3, STATUS_CHAR_UUID,
                value=[], notifying=False,
                flags=['notify','read'],
                read_callback=lambda _o: list(b""),
            )
            ble.publish()
        except Exception as e:
            log_debug(f"GATT error: {e}")
        time.sleep(5)

def start_gatt_server_thread():
    threading.Thread(target=start_gatt_server, daemon=True).start()

# ─────────────────────────── Build GUI ─────────────────────────────────
root = tb.Window(themename="litera")
root.style.colors.set("info", GREEN)
root.style.configure("TFrame", background="black")
root.style.configure("Status.TLabel",
                     background="black", foreground=GREEN,
                     font=("Helvetica", 48))
root.configure(bg="black")
root.title("Frame Status")
root.attributes("-fullscreen", True)
root.bind("<Escape>", lambda e: root.attributes("-fullscreen", False))
root.after_idle(_show_next_toast)

center = ttk.Frame(root, style="TFrame")
center.pack(expand=True)

status_label = ttk.Label(center, text="Checking Wi-Fi…", style="Status.TLabel")
status_label.pack()

load_spinner()
spinner_label = tk.Label(center, bg="black", bd=0, highlightthickness=0)

disable_pairing()
start_gatt_server_thread()
update_status()

root.mainloop()