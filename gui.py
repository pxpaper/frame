#!/usr/bin/env python3
# Pixel Paper full-screen status GUI
import tkinter as tk
import tkinter.font as tkfont
import socket
import subprocess
import time
import threading
import os
from bluezero import adapter, peripheral

# --- project-internal import --------------------------------------------------
import launch           # ← brings in update_repo()

# ── brand palette ─────────────────────────────────────────────────────────────
BRAND_BG        = "#010101"   # almost-black
BRAND_FG        = "#1FC742"   # bright green
BRAND_FG_DARK   = "#025B18"   # darker green
BRAND_BG_ALT    = "#161616"   # grey-black for debug panel

# ── globals (mostly unchanged from previous version) ──────────────────────────
launched          = False
debug_messages    = []
provisioning_char = None
repo_updated      = False
FAIL_MAX          = 3
fail_count        = 0
chromium_process  = None

PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"
SERIAL_CHAR_UUID          = "12345678-1234-5678-1234-56789abcdef2"

# ── toast log manager ──────────────────────────────────────────────────────
class ToastManager:
    """Creates temporary stacked labels that fade & self-destruct."""
    def __init__(self, root):
        self.root  = root
        self.frame = tk.Frame(root, bg="", highlightthickness=0)
        self.frame.place(relx=1.0, rely=0.0, x=-20, y=20, anchor="ne")
        self.toasts = []            # [(label, death_epoch), ...]

    def add(self, msg, duration=6000):
        lbl = tk.Label(self.frame, text=msg, font=("Courier", 12),
                       bg=BRAND_FG_DARK, fg="white", bd=0,
                       padx=10, pady=4, anchor="e", justify="right")
        lbl.pack(side="top", anchor="e", pady=4)
        death = int(time.time() * 1000) + duration
        self.toasts.append((lbl, death))
        self._schedule_check()

    def _schedule_check(self):
        if not hasattr(self, "_job"):
            self._job = self.root.after(500, self._check)

    def _check(self):
        now = int(time.time() * 1000)
        self.toasts = [(l, d) for (l, d) in self.toasts
                       if self._maybe_destroy(l, d, now)]
        if self.toasts:
            self._job = self.root.after(500, self._check)
        else:
            self._job = None

    def _maybe_destroy(self, label, death, now):
        if now >= death:
            label.destroy()
            return False
        remaining = death - now
        if remaining < 1500:
            alpha = remaining / 1500
            grey  = int(255 * (1 - alpha))
            colour = f"#{grey:02x}{grey:02x}{grey:02x}"
            label.configure(fg=colour)
        return True

# ── util helpers (unchanged / lightly tweaked for logging colours) ────────────
def get_serial_number():
    try:
        with open('/proc/device-tree/serial-number', 'r') as f:
            serial = f.read().strip('\x00\n ')
        return "PX" + serial
    except Exception:
        return "PXunknown"

def log_debug(message: str):
    print(message)         # still print to stdout
    toast.add(message)     # visible toast

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

# ── main status polling & animation ───────────────────────────────────────────
def update_status():
    """Poll connectivity and manage Chromium / repo-update side-effects."""
    global chromium_process, fail_count, repo_updated

    online = check_wifi_connection()
    if online:
        fail_count = 0
        set_status("Online ✔", BRAND_FG)

        if not repo_updated:
            threading.Thread(target=launch.update_repo, daemon=True).start()
            repo_updated = True

        if chromium_process is None or chromium_process.poll() is not None:
            label.config(text="Launching frame …")
            subprocess.run(["pkill", "-f", "chromium"], check=False)
            url = f"https://pixelpaper.com/frame.html?id={get_serial_number()}"
            chromium_process = subprocess.Popen(["chromium", "--kiosk", url])
    else:
        fail_count += 1
        set_status("Offline …", BRAND_FG_DARK)

        if fail_count >= FAIL_MAX:
            nm_reconnect()
            fail_count = 0

    # schedule next poll
    root.after(3_000, update_status)

# ── responsive UI helpers ─────────────────────────────────────────────────────
def set_status(text: str, colour: str):
    """Update the on-screen label and start a gentle pulse animation."""
    label.config(text=text, fg=colour)
    pulse(colour, 0)

def pulse(colour: str, step: int):
    """Simple heartbeat: fade between bright & dark green."""
    # 0 → 100 → 0
    ratio = step / 100
    if ratio > 1:
        ratio = 2 - ratio
    new_colour = blend(colour, BRAND_BG, ratio * 0.5)  # subtle
    canvas.itemconfig(pulse_circle, fill=new_colour)
    next_step = (step + 4) % 200
    root.after(40, pulse, colour, next_step)

def blend(c1: str, c2: str, t: float) -> str:
    """Linear-interpolate between two #rrggbb colours."""
    a = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    b = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    c = tuple(int(ai + (bi-ai)*t) for ai, bi in zip(a, b))
    return "#%02x%02x%02x" % c

def on_resize(event):
    """Re-scale fonts & visual elements to fit new geometry."""
    shorter_side = min(event.width, event.height)
    new_size = max(16, int(shorter_side * 0.06))  # 6 % of short edge
    status_font.configure(size=new_size)

    # pulse indicator radius = 8 % of short edge
    r = int(shorter_side * 0.08)
    canvas.coords(pulse_circle,
                  event.width/2 - r, event.height/2 - r - new_size,
                  event.width/2 + r, event.height/2 + r - new_size)

# ── BLE handling (unchanged except for log colour) ────────────────────────────
def handle_wifi_data(data: str):
    """
    Format:  SSID;PASS:secret
    Replaces all existing Wi-Fi profiles with one keyfile profile.
    """
    log_debug("Handling WiFi data: " + data)
    try:
        ssid, pass_part = data.split(';', 1)
        password = pass_part.split(':', 1)[1]
    except ValueError:
        log_debug("WiFi payload malformed; expected SSID;PASS:pwd")
        return

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
        log_debug(f"Activated Wi-Fi connection '{ssid}' non-interactively.")
    except subprocess.CalledProcessError as e:
        log_debug(f"nmcli error {e.returncode}: {e.stderr.strip() or e.stdout.strip()}")

def handle_orientation_change(data: str):
    """Rotate display via kanshi (unchanged)."""
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
}}
"""
    cfg_path = os.path.expanduser("~/.config/kanshi/config")
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    with open(cfg_path, "w") as f:
        f.write(cfg)
    os.chmod(cfg_path, 0o600)
    subprocess.run(["killall", "kanshi"], check=False)
    subprocess.Popen(["kanshi", "-c", cfg_path],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log_debug(f"Rotated {output} → {data}° via kanshi")

def ble_callback(value, options):
    try:
        if not value:
            return
        value_bytes = bytes(value) if isinstance(value, list) else value
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
            log_debug("Using Bluetooth adapter: " + dongle_addr)

            ble_periph = peripheral.Peripheral(dongle_addr, local_name="PixelPaper")
            ble_periph.add_service(srv_id=1, uuid=PROVISIONING_SERVICE_UUID, primary=True)
            provisioning_char = ble_periph.add_characteristic(
                srv_id=1, chr_id=1, uuid=PROVISIONING_CHAR_UUID,
                value=[], notifying=False,
                flags=['write', 'write-without-response'],
                write_callback=ble_callback
            )
            ble_periph.add_characteristic(
                srv_id=1, chr_id=2, uuid=SERIAL_CHAR_UUID,
                value=list(get_serial_number().encode()),
                notifying=False, flags=['read'],
                read_callback=lambda options: list(get_serial_number().encode())
            )
            log_debug("Publishing GATT server …")
            ble_periph.publish()
            log_debug("GATT event loop ended.")
        except Exception as e:
            log_debug("Exception in start_gatt_server: " + str(e))
        log_debug("Restarting GATT in 5 s …")
        time.sleep(5)

def start_gatt_server_thread():
    threading.Thread(target=start_gatt_server, daemon=True).start()

# ── Tkinter UI setup ──────────────────────────────────────────────────────────
root = tk.Tk()
root.title("Pixel Paper Status")
root.configure(bg=BRAND_BG)
root.attributes("-fullscreen", True)            # always full-screen
root.bind("<Configure>", on_resize)             # responsive sizing

# status text
status_font = tkfont.Font(family="Helvetica", size=48, weight="bold")
label = tk.Label(root, text="Starting …", font=status_font,
                 bg=BRAND_BG, fg=BRAND_FG)
label.pack(side=tk.TOP, pady=40)

# animated pulse indicator
canvas = tk.Canvas(root, bg=BRAND_BG, highlightthickness=0)
canvas.pack(fill=tk.BOTH, expand=True)
pulse_circle = canvas.create_oval(0, 0, 0, 0, fill=BRAND_FG, width=0)

# instantiate toast manager after canvas
toast = ToastManager(root)

# ── kick-off ──────────────────────────────────────────────────────────────────
disable_pairing()
start_gatt_server_thread()
update_status()            # first poll → periodic via .after
root.mainloop()
