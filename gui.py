#!/usr/bin/env python3
"""
Pixel Paper – Full-screen status / provisioning GUI
───────────────────────────────────────────────────
• Runs between launch.py and Chromium
• Portrait/landscape, auto-scaling fonts
• Brand palette: 010101  | 1FC742 | 025B18 | 161616
• Smooth toast notifications that stack and animate
• All original Wi-Fi, BLE, kanshi-rotation and git-update logic retained
"""
from __future__ import annotations
import os, socket, subprocess, threading, time, tkinter as tk
import tkinter.font as tkfont
from typing import List, Optional
from bluezero import adapter, peripheral
import launch                    # update_repo() + get_serial_number()

# ──────────────────────────────────────────────────────────────────────────
#  Palette
# ──────────────────────────────────────────────────────────────────────────
CLR_BG      = "#010101"
CLR_ACCENT  = "#1FC742"
CLR_ACCENT2 = "#025B18"   # toast background
CLR_TEXT    = "#E8E8E8"

# ──────────────────────────────────────────────────────────────────────────
#  Toast system – smooth & stackable
# ──────────────────────────────────────────────────────────────────────────
class Toast:
    WIDTH       = 380
    PAD         = 12
    MARGIN_X    = 20
    MARGIN_Y    = 20
    SPACING_Y   = 10
    SLIDE_MS    = 250        # into screen
    FADE_MS     = 400        # fade-out
    ALIVE_MS    = 4_000      # fully visible time

    active: List["Toast"] = []   # global stack (top→bottom)

    def __init__(self, master: tk.Tk, text: str):
        self.master = master
        self.frame  = tk.Frame(master, bg=CLR_ACCENT2, highlightthickness=0)
        self.label  = tk.Label(self.frame, text=text, fg=CLR_TEXT, bg=CLR_ACCENT2,
                               justify="left", wraplength=self.WIDTH - 2*self.PAD)
        self.label.pack(padx=self.PAD, pady=(self.PAD, self.PAD-2), anchor="w")

        # ensure geometry known
        self.frame.update_idletasks()
        self.height = self.frame.winfo_height()

        # compute initial & target positions
        self.y_target = self._calc_target_y(new_toast=True)
        x_start  = self.WIDTH + self.MARGIN_X
        x_final  = -self.MARGIN_X

        # place off-screen first (anchor NE keeps right-edge alignment)
        self.frame.place(relx=1.0, x=x_start, y=self.y_target, anchor="ne")

        Toast.active.append(self)
        self._slide_in(x_start, x_final)
        self.master.after(self.ALIVE_MS, self._fade_and_destroy)

    # ───────────────────────── stack helpers ────────────────────────────
    @classmethod
    def _calc_target_y(cls, new_toast: bool = False) -> int:
        """
        Return y for the *next* toast or reflow current ones.
        If new_toast=True we compute y where the freshly added toast goes.
        """
        y = cls.MARGIN_Y
        for t in cls.active:
            y += t.height + cls.SPACING_Y
        return y - (0 if new_toast else cls.height + cls.SPACING_Y)

    @classmethod
    def reflow(cls):
        """Animate all existing toasts to their new y-positions."""
        y = cls.MARGIN_Y
        for t in cls.active:
            if abs(t.frame.winfo_y() - y) > 1:
                t._animate_y(to=y)
            y += t.height + cls.SPACING_Y

    # ───────────────────────── animations ───────────────────────────────
    def _slide_in(self, x_start: int, x_final: int):
        frames = max(1, int(self.SLIDE_MS / 16))
        dx     = (x_start - x_final) / frames

        def step(i=0):
            if i >= frames:
                self.frame.place_configure(x=x_final)
                return
            self.frame.place_configure(x=x_start - dx*i)
            self.master.after(16, step, i+1)
        step()

    def _animate_y(self, to: int):
        current = self.frame.winfo_y()
        frames  = 10
        dy      = (to - current) / frames

        def step(i=0):
            if i >= frames:
                self.frame.place_configure(y=to)
                return
            self.frame.place_configure(y=current + dy*i)
            self.master.after(16, step, i+1)
        step()

    def _fade_and_destroy(self):
        frames = max(1, int(self.FADE_MS / 50))
        def fade(i=0):
            if i >= frames:
                self.frame.destroy()
                Toast.active.remove(self)
                Toast.reflow()
                return
            alpha = 1 - i / frames
            new_bg = _blend(CLR_ACCENT2, CLR_BG, 1 - alpha)
            new_fg = _blend(CLR_TEXT,   CLR_BG, 1 - alpha)
            self.frame.configure(bg=new_bg)
            self.label.configure(bg=new_bg, fg=new_fg)
            self.master.after(50, fade, i+1)
        fade()

def _blend(hex1: str, hex2: str, t: float) -> str:
    """Linear blend between two #rrggbb colours."""
    c1 = tuple(int(hex1[i:i+2],16) for i in (1,3,5))
    c2 = tuple(int(hex2[i:i+2],16) for i in (1,3,5))
    r  = int(c1[0] + (c2[0]-c1[0])*t)
    g  = int(c1[1] + (c2[1]-c1[1])*t)
    b  = int(c1[2] + (c2[2]-c1[2])*t)
    return f"#{r:02x}{g:02x}{b:02x}"

def log_debug(msg: str):
    print(msg)                      # still to stdout / journald
    root.after(0, Toast, root, msg) # schedule toast on UI thread
    root.after(0, Toast.reflow)     # gently push older toasts down

# ──────────────────────────────────────────────────────────────────────────
#  BLE UUIDs (unchanged)
# ──────────────────────────────────────────────────────────────────────────
PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"
SERIAL_CHAR_UUID          = "12345678-1234-5678-1234-56789abcdef2"

# ──────────────────────────────────────────────────────────────────────────
#  Original helper functions (Wi-Fi, kanshi, etc.)
# ──────────────────────────────────────────────────────────────────────────
def get_serial_number() -> str:
    try:
        with open('/proc/device-tree/serial-number', 'r') as f:
            serial = f.read().strip('\x00\n ')
        return "PX" + serial
    except Exception:
        return "PXunknown"

def check_wifi_connection(retries: int = 2) -> bool:
    for _ in range(retries):
        try:
            s = socket.create_connection(("8.8.8.8", 53), timeout=2); s.close()
            return True
        except OSError:
            time.sleep(0.25)
    return False

def nm_reconnect():
    try:
        ssid = subprocess.check_output(
            ["nmcli", "-t", "-f", "NAME,TYPE,DEVICE,ACTIVE",
             "connection", "show", "--active"],
            text=True
        ).split(':')[0]
        subprocess.run(["nmcli", "connection", "up", ssid], check=False)
        log_debug(f"nmcli reconnect issued for {ssid}")
    except Exception as e:
        log_debug(f"nm_reconnect err: {e}")

# ──────────────────────────────────────────────────────────────────────────
#  Network / Chromium watchdog
# ──────────────────────────────────────────────────────────────────────────
chromium_proc: Optional[subprocess.Popen] = None
repo_updated  = False
fail_count    = 0
FAIL_MAX      = 3

def update_status():
    global chromium_proc, repo_updated, fail_count
    online = check_wifi_connection()
    if online:
        status_lbl.config(text="Connected ✓", fg=CLR_ACCENT)
        if fail_count:
            fail_count = 0
        if not repo_updated:
            threading.Thread(target=launch.update_repo, daemon=True).start()
            repo_updated = True
        if chromium_proc is None or chromium_proc.poll() is not None:
            url = f"https://pixelpaper.com/frame.html?id={get_serial_number()}"
            subprocess.run(["pkill", "-f", "chromium"], check=False)
            chromium_proc = subprocess.Popen(["chromium", "--kiosk", url])
            log_debug("Chromium launched for frame display.")
    else:
        if fail_count < FAIL_MAX:
            fail_count += 1
            status_lbl.config(text="Waiting for Wi-Fi…", fg=CLR_TEXT)
        else:
            status_lbl.config(text="Offline ⚠", fg="#ff9933")
            nm_reconnect()
    root.after(3_000, update_status)

# ──────────────────────────────────────────────────────────────────────────
#  BLE provisioning, orientation, etc. (logic unchanged except log_debug)
# ──────────────────────────────────────────────────────────────────────────
def handle_wifi_data(data: str):
    log_debug("Handling Wi-Fi data: " + data)
    try: ssid, pass_part = data.split(';', 1); password = pass_part.split(':',1)[1]
    except ValueError:
        log_debug("Wi-Fi payload malformed; expected SSID;PASS:pwd"); return
    try:
        profiles = subprocess.check_output(
            ["nmcli","-t","-f","UUID,TYPE","connection","show"], text=True
        ).splitlines()
        for line in profiles:
            uuid, ctype = line.split(':',1)
            if ctype == "802-11-wireless":
                subprocess.run(["nmcli","connection","delete",uuid],
                               check=False,capture_output=True,text=True)
    except subprocess.CalledProcessError as e:
        log_debug(f"Could not list profiles: {e.stderr.strip()}")
    try:
        subprocess.run([
            "nmcli","connection","add","type","wifi",
            "ifname","wlan0","con-name",ssid,"ssid",ssid,
            "wifi-sec.key-mgmt","wpa-psk","wifi-sec.psk",password,
            "802-11-wireless-security.psk-flags","0",
            "connection.autoconnect","yes"
        ],check=True,capture_output=True,text=True)
        subprocess.run(["nmcli","connection","reload"],check=True)
        subprocess.run(["nmcli","connection","up",ssid],check=True,
                       capture_output=True,text=True)
        log_debug(f"Activated Wi-Fi connection '{ssid}'.")
    except subprocess.CalledProcessError as e:
        log_debug(f"nmcli error {e.returncode}: {e.stderr.strip() or e.stdout.strip()}")

def handle_orientation_change(data: str):
    output = "HDMI-A-1"
    try:
        mode = subprocess.check_output(
            "wlr-randr | grep '(current)' | awk '{print $1\"@\"$3}'",
            shell=True, text=True
        ).strip()
    except subprocess.CalledProcessError as e:
        log_debug(f"Failed to detect current mode: {e}")
        return
    cfg = (f"profile {{\n"
           f"  output {output} enable mode {mode} position 0,0 transform {data}\n"
           f"}}\n")
    cfg_path = os.path.expanduser("~/.config/kanshi/config")
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    with open(cfg_path, "w") as f: f.write(cfg)
    os.chmod(cfg_path, 0o600)
    subprocess.run(["killall","kanshi"],check=False)
    subprocess.Popen(["kanshi","-c",cfg_path],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log_debug(f"Rotated display → {data}°")

def ble_callback(value, options):
    try:
        if value is None: return
        value_bytes = (bytes(value)        if isinstance(value, list)
                       else bytes(value)   if isinstance(value,(bytes,bytearray))
                       else None)
        if value_bytes is None:
            log_debug(f"Unexpected BLE value type: {type(value)}"); return
        msg = value_bytes.decode("utf-8",errors="ignore").strip()
        log_debug("Received BLE data: " + msg)
        if   msg.startswith("WIFI:"):   handle_wifi_data(msg[5:].strip())
        elif msg.startswith("ORIENT:"): handle_orientation_change(msg[7:].strip())
        elif msg == "REBOOT":           subprocess.run(["sudo","reboot"],check=False)
        else:                           log_debug("Unknown BLE command.")
    except Exception as e:
        log_debug("Error in ble_callback: " + str(e))

def start_gatt_server():
    while True:
        try:
            dongles = adapter.Adapter.available()
            if not dongles:
                log_debug("No Bluetooth adapters available."); time.sleep(4); continue
            addr = list(dongles)[0].address
            p = peripheral.Peripheral(addr, local_name="PixelPaper")
            p.add_service(1, PROVISIONING_SERVICE_UUID, primary=True)
            p.add_characteristic(
                1, 1, PROVISIONING_CHAR_UUID, value=[], notifying=False,
                flags=['write','write-without-response'], write_callback=ble_callback)
            p.add_characteristic(
                1, 2, SERIAL_CHAR_UUID,
                value=list(get_serial_number().encode()),
                notifying=False, flags=['read'],
                read_callback=lambda _: list(get_serial_number().encode()))
            log_debug("Publishing GATT provisioning service…")
            p.publish()
        except Exception as e:
            log_debug(f"GATT server error: {e}")
        log_debug("Restarting GATT server in 5 s…")
        time.sleep(5)

def start_gatt_thread():
    threading.Thread(target=start_gatt_server, daemon=True).start()

def disable_pairing():
    try:
        subprocess.run(["bluetoothctl"],
                       input="pairable no\nquit\n", text=True,
                       capture_output=True, check=True)
    except Exception as e:
        log_debug("Failed to disable pairing: " + str(e))

# ──────────────────────────────────────────────────────────────────────────
#  Tkinter full-screen UI
# ──────────────────────────────────────────────────────────────────────────
root = tk.Tk()
root.title("Pixel Paper – Setup")
root.configure(bg=CLR_BG)
root.attributes('-fullscreen', True)
root.bind("<Escape>", lambda e: None)    # ignore Esc

status_font = tkfont.Font(family="Helvetica", size=64, weight="bold")
status_lbl  = tk.Label(root, text="Checking Wi-Fi…",
                       fg=CLR_TEXT, bg=CLR_BG, font=status_font)
status_lbl.pack(expand=True)

def _autoscale(event=None):
    status_font.configure(size=max(root.winfo_width(),root.winfo_height())//18)
root.bind("<Configure>", _autoscale)

# ──────────────────────────────────────────────────────────────────────────
#  Boot sequence
# ──────────────────────────────────────────────────────────────────────────
disable_pairing()
start_gatt_thread()
root.after(200, update_status)      # kick watchdog after small delay
root.mainloop()
