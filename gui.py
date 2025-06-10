#!/usr/bin/env python3
"""
Pixel Paper – Full-screen status / provisioning GUI
───────────────────────────────────────────────────
• Runs between launch.py and Chromium on a headless frame
• Portrait or landscape, auto-scaling fonts
• Brand palette: 010101 / 1FC742 / 025B18 / 161616
• Smooth, vertically stacking toast notifications at 50 FPS
• All original Wi-Fi, BLE, kanshi-rotation, and git-update logic retained
"""
from __future__ import annotations
import os
import socket
import subprocess
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from typing import List, Optional

from bluezero import adapter, peripheral
import launch  # for update_repo() and get_serial_number()

# ──────────────────────────────────────────────────────────────────────────
#  Brand colours
# ──────────────────────────────────────────────────────────────────────────
CLR_BG      = "#010101"
CLR_ACCENT  = "#1FC742"
CLR_ACCENT2 = "#025B18"   # toast background
CLR_TEXT    = "#E8E8E8"

# ──────────────────────────────────────────────────────────────────────────
#  Toast system – smooth, stacked, 50 FPS
# ──────────────────────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────
#  Toast system – one global 60 fps animation loop
# ──────────────────────────────────────────────────────────────────────────
class Toast:
    WIDTH       = 380
    PAD         = 12
    MARGIN_X    = 20
    MARGIN_Y    = 20
    SPACING_Y   = 10
    SLIDE_PX    = 24          # px per frame for X-slide (~250 ms)
    FADE_PCT    = 0.05        # α decrement per frame during fade
    SHOW_FRAMES = 240         # ≈ 4 s at 60 fps

    active : list["Toast"] = []      # keeps z-order

    # -- one global animation clock --------------------------------------
    _ticker_started = False
    @classmethod
    def _start_ticker(cls):
        if cls._ticker_started: return
        cls._ticker_started = True
        def tick():
            for t in cls.active[:]:
                t._update()
            root.after(16, tick)
        tick()

    # --------------------------------------------------------------------
    def __init__(self, master: tk.Tk, text: str):
        self.master   = master
        self.state    = 'slide'   # 'slide' → 'show' → 'fade'
        self.framectr = 0
        self.alpha    = 1.0
        # build widget
        self.frame = tk.Frame(master, bg=CLR_ACCENT2, highlightthickness=0)
        self.label = tk.Label(self.frame, text=text, fg=CLR_TEXT, bg=CLR_ACCENT2,
                              justify="left", wraplength=self.WIDTH-2*self.PAD)
        self.label.pack(padx=self.PAD, pady=(self.PAD,self.PAD-2), anchor='w')
        # fetch natural height
        self.frame.update_idletasks()
        self.height = self.frame.winfo_height()

        # reserve spot **before** adding to list → no overlap ever
        self.y = self._reserved_y()
        self.x = self.WIDTH + self.MARGIN_X
        self.frame.place(relx=1.0, x=self.x, y=self.y, anchor='ne')

        Toast.active.append(self)
        Toast._start_ticker()

    # --------------------------------------------------------------------
    def _reserved_y(self) -> int:
        y = self.MARGIN_Y
        for t in Toast.active:
            y += t.height + self.SPACING_Y
        return y

    # --------------------------------------------------------------------
    def _update(self):
        # slide in
        if self.state == 'slide':
            self.x -= self.SLIDE_PX
            if self.x <= -self.MARGIN_X:
                self.x = -self.MARGIN_X
                self.state = 'show'
            self.frame.place_configure(x=self.x)

        # show countdown
        elif self.state == 'show':
            if self.framectr >= self.SHOW_FRAMES:
                self.state = 'fade'
            else:
                self.framectr += 1

        # fade out
        elif self.state == 'fade':
            self.alpha -= self.FADE_PCT
            if self.alpha <= 0:
                self._destroy()
                return
            new_bg = _blend(CLR_ACCENT2, CLR_BG, 1-self.alpha)
            new_fg = _blend(CLR_TEXT,   CLR_BG, 1-self.alpha)
            self.frame.configure(bg=new_bg)
            self.label.configure(bg=new_bg, fg=new_fg)

        # keep vertical stack tidy (gentle spring)
        target_y = self._reserved_y_position()
        if abs(self.y - target_y) > 1:
            self.y += (target_y - self.y) * 0.25   # ease-to-target
            self.frame.place_configure(y=int(self.y))

    # --------------------------------------------------------------------
    def _reserved_y_position(self) -> int:
        y = self.MARGIN_Y
        for t in Toast.active:
            if t is self: break
            y += t.height + self.SPACING_Y
        return y

    # --------------------------------------------------------------------
    def _destroy(self):
        self.frame.destroy()
        Toast.active.remove(self)


def _blend(c1: str, c2: str, t: float) -> str:
    """Linear blend two #rrggbb colours at t [0..1]"""
    r1, g1, b1 = int(c1[1:3],16), int(c1[3:5],16), int(c1[5:7],16)
    r2, g2, b2 = int(c2[1:3],16), int(c2[3:5],16), int(c2[5:7],16)
    r = int(r1 + (r2-r1)*t)
    g = int(g1 + (g2-g1)*t)
    b = int(b1 + (b2-b1)*t)
    return f"#{r:02x}{g:02x}{b:02x}"

def log_debug(msg: str):
    """Print to stdout and create a new toast notification."""
    print(msg)
    Toast(root, msg)

def animate_toasts():
    """Global animation loop for all toasts at ~50 FPS."""
    now = time.time()
    to_remove: List[Toast] = []

    # update each toast
    for idx, toast in enumerate(Toast.active):
        elapsed = now - toast.start_time

        # 1) slide-in phase
        if elapsed < Toast.SLIDE_DUR:
            p = elapsed / Toast.SLIDE_DUR
            toast.current_x = toast.start_x - p * (toast.start_x - toast.final_x)
        else:
            toast.current_x = toast.final_x

        # 2) vertical stack target
        target_y = Toast.MARGIN_Y
        for prev in Toast.active[:idx]:
            target_y += prev.height + Toast.SPACING_Y
        # spring / easing to move current_y toward target_y
        dy = (target_y - toast.current_y) * 0.2
        toast.current_y += dy

        # 3) fade-out phase
        fade_start = Toast.SLIDE_DUR + Toast.VISIBLE_DUR
        if elapsed > fade_start:
            fade_p = min((elapsed - fade_start) / Toast.FADE_DUR, 1.0)
            # blend towards background
            bg = _blend(CLR_ACCENT2, CLR_BG, fade_p)
            fg = _blend(CLR_TEXT,   CLR_BG, fade_p)
            toast.frame.configure(bg=bg)
            toast.label.configure(bg=bg, fg=fg)
            if fade_p >= 1.0:
                toast.frame.destroy()
                to_remove.append(toast)

        # apply geometry
        toast.frame.place_configure(x=int(toast.current_x),
                                    y=int(toast.current_y))

    # remove any finished toasts
    for t in to_remove:
        Toast.active.remove(t)

    # schedule next frame if any remain
    if Toast.active:
        root.after(20, animate_toasts)


# ──────────────────────────────────────────────────────────────────────────
#  Original helpers (Wi-Fi, BLE, rotation, etc.)
# ──────────────────────────────────────────────────────────────────────────
def get_serial_number() -> str:
    try:
        with open('/proc/device-tree/serial-number','r') as f:
            s = f.read().strip('\x00\n ')
        return "PX" + s
    except:
        return "PXunknown"

def check_wifi_connection(retries: int = 2) -> bool:
    for _ in range(retries):
        try:
            s = socket.create_connection(("8.8.8.8", 53), timeout=2)
            s.close()
            return True
        except OSError:
            time.sleep(0.25)
    return False

def nm_reconnect():
    try:
        ssid = subprocess.check_output(
            ["nmcli","-t","-f","NAME,TYPE,DEVICE,ACTIVE",
             "connection","show","--active"],
            text=True
        ).split(':')[0]
        subprocess.run(["nmcli","connection","up",ssid], check=False)
        log_debug(f"nmcli reconnect issued for {ssid}")
    except Exception as e:
        log_debug(f"nm_reconnect err: {e}")

# ──────────────────────────────────────────────────────────────────────────
#  Network & Chromium watchdog
# ──────────────────────────────────────────────────────────────────────────
chromium_proc: Optional[subprocess.Popen] = None
repo_updated  = False
fail_count    = 0
FAIL_MAX      = 3

def update_status():
    global chromium_proc, repo_updated, fail_count
    up = check_wifi_connection()
    if up:
        status_lbl.config(text="Connected ✓", fg=CLR_ACCENT)
        if fail_count:
            fail_count = 0
        if not repo_updated:
            threading.Thread(target=launch.update_repo, daemon=True).start()
            repo_updated = True
        if chromium_proc is None or chromium_proc.poll() is not None:
            url = f"https://pixelpaper.com/frame.html?id={get_serial_number()}"
            subprocess.run(["pkill","-f","chromium"], check=False)
            chromium_proc = subprocess.Popen(["chromium","--kiosk",url])
            log_debug("Chromium launched.")
    else:
        if fail_count < FAIL_MAX:
            fail_count += 1
            status_lbl.config(text="Waiting for Wi-Fi…", fg=CLR_TEXT)
        else:
            status_lbl.config(text="Offline ⚠", fg="#ff9933")
            nm_reconnect()
    root.after(3000, update_status)

# ──────────────────────────────────────────────────────────────────────────
#  BLE provisioning, orientation, etc. (identical logic, log_debug used)
# ──────────────────────────────────────────────────────────────────────────
def handle_wifi_data(data: str):
    log_debug("Handling Wi-Fi data: " + data)
    try:
        ssid, pass_part = data.split(';',1)
        password = pass_part.split(':',1)[1]
    except ValueError:
        log_debug("Malformed Wi-Fi payload.")
        return
    # delete old
    try:
        profiles = subprocess.check_output(
            ["nmcli","-t","-f","UUID,TYPE","connection","show"], text=True
        ).splitlines()
        for line in profiles:
            uuid, ctype = line.split(':',1)
            if ctype == "802-11-wireless":
                subprocess.run(["nmcli","connection","delete",uuid],
                               check=False, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        log_debug(f"List profiles error: {e.stderr.strip()}")
    # add new
    try:
        subprocess.run([
            "nmcli","connection","add","type","wifi",
            "ifname","wlan0","con-name",ssid,"ssid",ssid,
            "wifi-sec.key-mgmt","wpa-psk","wifi-sec.psk",password,
            "802-11-wireless-security.psk-flags","0",
            "connection.autoconnect","yes"
        ], check=True, capture_output=True, text=True)
        subprocess.run(["nmcli","connection","reload"], check=True)
        subprocess.run(["nmcli","connection","up",ssid], check=True,
                       capture_output=True, text=True)
        log_debug(f"Activated Wi-Fi '{ssid}'.")
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
        log_debug(f"Detect mode failed: {e}")
        return
    cfg = (f"profile {{\n"
           f"  output {output} enable mode {mode} position 0,0 transform {data}\n"
           f"}}\n")
    cfg_path = os.path.expanduser("~/.config/kanshi/config")
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    with open(cfg_path,"w") as f: f.write(cfg)
    os.chmod(cfg_path, 0o600)
    subprocess.run(["killall","kanshi"], check=False)
    subprocess.Popen(["kanshi","-c",cfg_path],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log_debug(f"Rotated display → {data}°")

def ble_callback(value, options):
    try:
        if value is None: return
        val_bytes = (bytes(value) if isinstance(value, list)
                     else bytes(value) if isinstance(value,(bytes,bytearray))
                     else None)
        if val_bytes is None:
            log_debug(f"Unexpected BLE type: {type(value)}"); return
        msg = val_bytes.decode("utf-8",errors="ignore").strip()
        log_debug("BLE data: " + msg)
        if msg.startswith("WIFI:"):
            handle_wifi_data(msg[5:].strip())
        elif msg.startswith("ORIENT:"):
            handle_orientation_change(msg[7:].strip())
        elif msg == "REBOOT":
            log_debug("Rebooting…"); subprocess.run(["sudo","reboot"],check=False)
        else:
            log_debug("Unknown BLE cmd.")
    except Exception as e:
        log_debug("ble_callback error: " + str(e))

def start_gatt_server():
    while True:
        try:
            dongles = adapter.Adapter.available()
            if not dongles:
                log_debug("No BT adapters."); time.sleep(5); continue
            addr = list(dongles)[0].address
            p = peripheral.Peripheral(addr, local_name="PixelPaper")
            p.add_service(1, PROVISIONING_SERVICE_UUID, primary=True)
            p.add_characteristic(
                1,1,PROVISIONING_CHAR_UUID,
                value=[], notifying=False,
                flags=['write','write-without-response'],
                write_callback=ble_callback
            )
            p.add_characteristic(
                1,2,SERIAL_CHAR_UUID,
                value=list(get_serial_number().encode()),
                notifying=False, flags=['read'],
                read_callback=lambda _: list(get_serial_number().encode())
            )
            log_debug("Publishing GATT…")
            p.publish()
        except Exception as e:
            log_debug("GATT server error: " + str(e))
        log_debug("Restarting GATT in 5s…")
        time.sleep(5)

def start_gatt_thread():
    threading.Thread(target=start_gatt_server, daemon=True).start()

def disable_pairing():
    try:
        subprocess.run(["bluetoothctl"],
                       input="pairable no\nquit\n",
                       text=True, capture_output=True, check=True)
    except Exception as e:
        log_debug("Disable pairing failed: " + str(e))


# ──────────────────────────────────────────────────────────────────────────
#  Full-screen Tkinter UI
# ──────────────────────────────────────────────────────────────────────────
root = tk.Tk()
root.title("Pixel Paper – Setup")
root.configure(bg=CLR_BG)
root.attributes('-fullscreen', True)
root.bind("<Escape>", lambda e: None)

status_font = tkfont.Font(family="Helvetica", size=64, weight="bold")
status_lbl  = tk.Label(root,
                       text="Checking Wi-Fi…",
                       fg=CLR_TEXT,
                       bg=CLR_BG,
                       font=status_font)
status_lbl.pack(expand=True)

def _autoscale(event=None):
    size = max(root.winfo_width(), root.winfo_height()) // 18
    status_font.configure(size=size)

root.bind("<Configure>", _autoscale)

# ──────────────────────────────────────────────────────────────────────────
#  Initialize services and start main loop
# ──────────────────────────────────────────────────────────────────────────
disable_pairing()
start_gatt_thread()
root.after(200, update_status)
root.mainloop()
