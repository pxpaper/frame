#!/usr/bin/env python3
"""
Pixel Paper – full-screen GUI (portrait & landscape friendly)
Keeps all previous functionality but adds a modern look and feel.
"""
import tkinter as tk
import socket, subprocess, time, threading, os, math
from bluezero import adapter, peripheral

# ── brand palette ────────────────────────────────────────────────────────
COLORS = {
    "bg"       : "#010101",
    "accent"   : "#1FC742",
    "accent2"  : "#025B18",
    "log_bg"   : "#161616",
    "text"     : "#FFFFFF",
}

# ── import launch helpers (update_repo etc.) ─────────────────────────────
import launch

# ── state flags kept from old script ─────────────────────────────────────
launched = False
repo_updated = False
fail_count  = 0
FAIL_MAX    = 3
chromium_process = None
provisioning_char = None

# ── BLE UUIDs (unchanged) ────────────────────────────────────────────────
PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"
SERIAL_CHAR_UUID          = "12345678-1234-5678-1234-56789abcdef2"

# ── helpers reused from old script ───────────────────────────────────────
def get_serial_number():
    try:
        with open('/proc/device-tree/serial-number', 'r') as f:
            serial = f.read().strip('\x00\n ')
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
        log_debug(f"Failed to disable pairing: {e}")

# ── UI helpers ───────────────────────────────────────────────────────────
class LogManager:
    """Toast-style logs that slide in at top-right and fade out."""
    def __init__(self, root):
        self.root = root
        self.cards = []

    def show(self, text, ttl=4000):
        card = tk.Label(self.root, text=text, fg=COLORS["text"], bg=COLORS["log_bg"],
                        font=("Helvetica", 14), bd=0, padx=14, pady=6, anchor="w")
        card.update_idletasks()

        # place off-screen first, then slide-in
        x = self.root.winfo_width() - card.winfo_reqwidth() - 12
        y = 12 + sum(c.winfo_reqheight() + 8 for c in self.cards)
        card.place(x=x + card.winfo_reqwidth() + 20, y=y)  # start just outside
        self.cards.append(card)

        # slide animation (10 frames)
        for i in range(10):
            self.root.after(i*20, lambda i=i, c=card, x=x: c.place(x=x + (10-i)*4))

        # schedule fade-out & cleanup
        self.root.after(ttl, lambda c=card: self._fade_and_remove(c))

    def _fade_and_remove(self, card, step=0):
        if step >= 10:
            card.destroy()
            self.cards.remove(card)
            self._reflow()
            return
        # simple fade by adjusting bg alpha via rgb interpolation
        ratio = 1 - step/10
        r = int(0x16 * ratio)  # 0x16 from #161616
        g = int(0x16 * ratio)
        b = int(0x16 * ratio)
        card.config(bg=f"#{r:02x}{g:02x}{b:02x}")
        self.root.after(40, lambda: self._fade_and_remove(card, step+1))

    def _reflow(self):
        """Re-stack remaining cards upward."""
        y = 12
        for card in self.cards:
            card.place(y=y)
            y += card.winfo_reqheight() + 8

class UIManager:
    """Controls the main status label and animations."""
    def __init__(self, root, log_mgr: LogManager):
        self.root = root
        self.log  = log_mgr
        self.status = tk.Label(root,
                               text="Checking Wi-Fi…",
                               fg=COLORS["accent"],
                               bg=COLORS["bg"],
                               font=("Helvetica", 48, "bold"))
        self.status.pack(expand=True)
        self.pulse_phase = 0
        root.bind('<Configure>', self._on_resize)
        self._animate_pulse()

    def set_status(self, text, ok=False):
        self.status.config(text=text,
                           fg=COLORS["accent"] if ok else COLORS["accent2"])

    # ――― small pulse animation to indicate activity ―――
    def _animate_pulse(self):
        self.pulse_phase = (self.pulse_phase + 1) % 100
        scale = 1 + 0.02*math.sin(self.pulse_phase/100*2*math.pi)
        self.status.tk.call(self.status._w, "scale", 0, 0, scale, scale)
        self.root.after(40, self._animate_pulse)

    # ――― keep font size proportional to window height ―――
    def _on_resize(self, event):
        h = event.height
        new_size = max(28, int(h * 0.10))
        self.status.config(font=("Helvetica", new_size, "bold"))

# ── logging bridge so old log_debug() keeps working ──────────────────────
log_mgr: LogManager = None
def log_debug(message):
    print(message)  # still mirror to stdout
    if log_mgr:
        log_mgr.show(message)

# ── Wi-Fi / Chromium monitor (unchanged behaviour) ───────────────────────
def update_status(ui: UIManager):
    global chromium_process, fail_count, repo_updated

    try:
        up = check_wifi_connection()
        if up:
            fail_count = 0
            if not repo_updated:
                threading.Thread(target=launch.update_repo, daemon=True).start()
                repo_updated = True

            ui.set_status("Wi-Fi OK – launching frame", ok=True)

            if chromium_process is None or chromium_process.poll() is not None:
                subprocess.run(["pkill", "-f", "chromium"], check=False)
                url = f"https://pixelpaper.com/frame.html?id={get_serial_number()}"
                chromium_process = subprocess.Popen(["chromium", "--kiosk", url])
        else:
            fail_count += 1
            ui.set_status("Waiting for Wi-Fi…" , ok=False)
            if fail_count >= FAIL_MAX:
                log_debug("Wi-Fi down – reconnecting NM")
                nm_reconnect()
                fail_count = 0
    except Exception as e:
        log_debug(f"update_status error: {e}")

    # schedule next check
    ui.root.after(4000, lambda: update_status(ui))

# ── NetworkManager reconnect helper (same logic) ─────────────────────────
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

# ── BLE provisioning bits  (no functional change; only log style) ───────
def handle_wifi_data(data: str):
    ···  #  ←  *identical body from your original script*  (omitted for brevity)

def handle_orientation_change(data):
    ···  #  ←  unchanged

def ble_callback(value, options):
    ···  #  ←  unchanged

def start_gatt_server():
    ···  #  ←  unchanged

def start_gatt_server_thread():
    t = threading.Thread(target=start_gatt_server, daemon=True)
    t.start()

# ── main entry ───────────────────────────────────────────────────────────
if __name__ == '__main__':
    root = tk.Tk()
    root.configure(bg=COLORS["bg"])
    root.attributes('-fullscreen', True)

    log_mgr = LogManager(root)
    ui      = UIManager(root, log_mgr)

    disable_pairing()
    start_gatt_server_thread()
    update_status(ui)

    root.mainloop()
