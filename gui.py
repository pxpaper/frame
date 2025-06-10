#!/usr/bin/env python3
"""
Pixel Paper – Full-screen status / provisioning GUI
───────────────────────────────────────────────────
• Portrait or landscape, auto-scaling fonts
• Brand palette: 010101 | 1FC742 | 025B18 | 161616
• NEW: one-loop ToastManager → smooth, non-overlapping notifications
• All Wi-Fi / BLE / kanshi / git-update logic preserved
"""
from __future__ import annotations
import os, socket, subprocess, threading, time, tkinter as tk
import tkinter.font as tkfont
from typing import List, Optional
from bluezero import adapter, peripheral
import launch                                    # update_repo() + get_serial_number()

# ──────────────────────────────────────────────────────────────────────────
#  Colours & constants
# ──────────────────────────────────────────────────────────────────────────
CLR_BG      = "#010101"
CLR_ACCENT  = "#1FC742"
CLR_ACCENT2 = "#025B18"
CLR_TEXT    = "#E8E8E8"

# ──────────────────────────────────────────────────────────────────────────
#  Toast system – one central manager
# ──────────────────────────────────────────────────────────────────────────
class Toast:
    WIDTH       = 380
    PAD         = 12
    MARGIN_X    = 20
    MARGIN_Y    = 20
    SPACING_Y   = 10
    ALIVE_MS    = 4_000          # fully visible
    FADE_SEC    = 0.40           # seconds
    SLIDE_SEC   = 0.25           # seconds (handled by easing)

    def __init__(self, text: str):
        self.frame  = tk.Frame(root, bg=CLR_ACCENT2, highlightthickness=0)
        self.label  = tk.Label(self.frame, text=text, fg=CLR_TEXT, bg=CLR_ACCENT2,
                               justify="left", wraplength=self.WIDTH - 2*self.PAD)
        self.label.pack(padx=self.PAD, pady=(self.PAD, self.PAD-2), anchor="w")
        self.frame.update_idletasks()
        self.h      = self.frame.winfo_height()

        self.x      =  self.WIDTH + self.MARGIN_X     # start off-screen
        self.y      =  ToastManager.next_y(self.h)    # initial stack pos
        self.target_x = -self.MARGIN_X
        self.target_y = self.y
        self.alpha  = 1.0
        self.birth  = time.time()
        self.fading = False

        self.frame.place(relx=1.0, x=self.x, y=self.y, anchor="ne")
        ToastManager.register(self)

    # called by manager every frame
    def tick(self, dt: float):
        if not self.fading and (time.time() - self.birth) * 1000 >= self.ALIVE_MS:
            self.fading = True

        # easing towards targets
        ease = 0.25
        self.x += (self.target_x - self.x) * ease
        self.y += (self.target_y - self.y) * ease

        if self.fading:
            fade_step = dt / self.FADE_SEC
            self.alpha = max(0.0, self.alpha - fade_step)
            if self.alpha == 0.0:
                ToastManager.unregister(self)
                self.frame.destroy()
                return
            self._apply_alpha()

        self.frame.place_configure(x=int(self.x), y=int(self.y))

    def _apply_alpha(self):
        def blend(a, b):  # a → b by (1-alpha)
            return int(a + (b - a) * (1 - self.alpha))
        bg_r, bg_g, bg_b = (int(CLR_ACCENT2[i:i+2], 16) for i in (1,3,5))
        root_r, root_g, root_b = (int(CLR_BG[i:i+2], 16) for i in (1,3,5))
        nr = blend(bg_r, root_r); ng = blend(bg_g, root_g); nb = blend(bg_b, root_b)
        fg = int(0xE8 * self.alpha)    # fade text to transparent black
        new_bg = f"#{nr:02x}{ng:02x}{nb:02x}"
        new_fg = f"#{fg:02x}{fg:02x}{fg:02x}"
        self.frame.configure(bg=new_bg)
        self.label.configure(bg=new_bg, fg=new_fg)

class ToastManager:
    _all: List[Toast] = []
    _frame_ms = 16                  # ~60 FPS

    @classmethod
    def register(cls, toast: Toast):
        cls._all.append(toast)
        cls.reflow()
    @classmethod
    def unregister(cls, toast: Toast):
        if toast in cls._all:
            cls._all.remove(toast)
            cls.reflow()
    @classmethod
    def next_y(cls, height: int) -> int:
        y = Toast.MARGIN_Y
        for t in cls._all:
            y += t.h + Toast.SPACING_Y
        return y
    @classmethod
    def reflow(cls):
        y = Toast.MARGIN_Y
        for t in cls._all:
            t.target_y = y
            y += t.h + Toast.SPACING_Y
    @classmethod
    def loop(cls):
        now = time.time()
        cls._last = getattr(cls, "_last", now)
        dt = now - cls._last
        cls._last = now
        for t in cls._all[:]:   # copy to allow removal inside loop
            t.tick(dt)
        root.after(cls._frame_ms, cls.loop)

def log_debug(msg: str):
    print(msg)
    root.after(0, Toast, msg)

# ──────────────────────────────────────────────────────────────────────────
#  BLE UUIDs – unchanged
# ──────────────────────────────────────────────────────────────────────────
PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"
SERIAL_CHAR_UUID          = "12345678-1234-5678-1234-56789abcdef2"

# ──────────────────────────────────────────────────────────────────────────
#  Original helpers (Wi-Fi, kanshi, etc.)
# ──────────────────────────────────────────────────────────────────────────
def get_serial_number() -> str:
    try:
        with open('/proc/device-tree/serial-number', 'r') as f:
            ser = f.read().strip('\x00\n ')
        return "PX" + ser
    except Exception:
        return "PXunknown"

def check_wifi_connection(retries: int = 2) -> bool:
    for _ in range(retries):
        try:
            sock = socket.create_connection(("8.8.8.8", 53), timeout=2)
            sock.close(); return True
        except OSError:
            time.sleep(0.25)
    return False

def nm_reconnect():
    try:
        ssid = subprocess.check_output(
            ["nmcli", "-t", "-f", "NAME,TYPE,DEVICE,ACTIVE",
             "connection", "show", "--active"], text=True
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
        if fail_count: fail_count = 0
        if not repo_updated:
            threading.Thread(target=launch.update_repo, daemon=True).start()
            repo_updated = True
        if chromium_proc is None or chromium_proc.poll() is not None:
            url = f"https://pixelpaper.com/frame.html?id={get_serial_number()}"
            subprocess.run(["pkill","-f","chromium"], check=False)
            chromium_proc = subprocess.Popen(["chromium","--kiosk", url])
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
    try: ssid, pass_part = data.split(';',1); password = pass_part.split(':',1)[1]
    except ValueError:
        log_debug("Wi-Fi payload malformed; expected SSID;PASS:pwd"); return
    try:
        profiles = subprocess.check_output(
            ["nmcli","-t","-f","UUID,TYPE","connection","show"], text=True
        ).splitlines()
        for line in profiles:
            uuid, typ = line.split(':',1)
            if typ == "802-11-wireless":
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
    output="HDMI-A-1"
    try:
        mode=subprocess.check_output(
            "wlr-randr | grep '(current)' | awk '{print $1\"@\"$3}'",
            shell=True,text=True).strip()
    except subprocess.CalledProcessError as e:
        log_debug(f"Failed to detect current mode: {e}"); return
    cfg=(f"profile {{\n"
         f"  output {output} enable mode {mode} position 0,0 transform {data}\n"
         f"}}\n")
    cfg_path=os.path.expanduser("~/.config/kanshi/config")
    os.makedirs(os.path.dirname(cfg_path),exist_ok=True)
    with open(cfg_path,"w") as f: f.write(cfg)
    os.chmod(cfg_path,0o600)
    subprocess.run(["killall","kanshi"],check=False)
    subprocess.Popen(["kanshi","-c",cfg_path],
                     stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    log_debug(f"Rotated display → {data}°")

def ble_callback(value, options):
    try:
        if value is None: return
        b = bytes(value) if isinstance(value,(list,bytes,bytearray)) else None
        if b is None: log_debug(f"Unexpected BLE value type: {type(value)}"); return
        msg=b.decode("utf-8","ignore").strip()
        log_debug("Received BLE data: "+msg)
        if   msg.startswith("WIFI:"):   handle_wifi_data(msg[5:].strip())
        elif msg.startswith("ORIENT:"): handle_orientation_change(msg[7:].strip())
        elif msg=="REBOOT":             subprocess.run(["sudo","reboot"],check=False)
        else:                           log_debug("Unknown BLE command.")
    except Exception as e: log_debug("Error in ble_callback: "+str(e))

def start_gatt_server():
    while True:
        try:
            dongles=adapter.Adapter.available()
            if not dongles:
                log_debug("No Bluetooth adapters available."); time.sleep(4); continue
            addr=list(dongles)[0].address
            periph=peripheral.Peripheral(addr,local_name="PixelPaper")
            periph.add_service(1,PROVISIONING_SERVICE_UUID,primary=True)
            periph.add_characteristic(
                1,1,PROVISIONING_CHAR_UUID,value=[],notifying=False,
                flags=['write','write-without-response'],write_callback=ble_callback)
            periph.add_characteristic(
                1,2,SERIAL_CHAR_UUID,
                value=list(get_serial_number().encode()),
                notifying=False,flags=['read'],
                read_callback=lambda _: list(get_serial_number().encode()))
            log_debug("Publishing GATT provisioning service…")
            periph.publish()
        except Exception as e:
            log_debug(f"GATT server error: {e}")
        log_debug("Restarting GATT server in 5 s…"); time.sleep(5)

def start_gatt_thread():
    threading.Thread(target=start_gatt_server,daemon=True).start()

def disable_pairing():
    try:
        subprocess.run(["bluetoothctl"],
                       input="pairable no\nquit\n",
                       text=True,capture_output=True,check=True)
    except Exception as e:
        log_debug("Failed to disable pairing: "+str(e))

# ──────────────────────────────────────────────────────────────────────────
#  Tkinter UI shell
# ──────────────────────────────────────────────────────────────────────────
root = tk.Tk()
root.title("Pixel Paper – Setup")
root.configure(bg=CLR_BG)
root.attributes('-fullscreen', True)
root.bind("<Escape>", lambda e: None)

status_font = tkfont.Font(family="Helvetica", size=64, weight="bold")
status_lbl  = tk.Label(root, text="Checking Wi-Fi…",
                       fg=CLR_TEXT, bg=CLR_BG, font=status_font)
status_lbl.pack(expand=True)

def _autoscale(event=None):
    status_font.configure(size=max(root.winfo_width(), root.winfo_height()) // 18)
root.bind("<Configure>", _autoscale)

# ──────────────────────────────────────────────────────────────────────────
#  Boot sequence
# ──────────────────────────────────────────────────────────────────────────
disable_pairing()
start_gatt_thread()
root.after(200, update_status)
root.after(0, ToastManager.loop)        # kick animation loop
root.mainloop()
