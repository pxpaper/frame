#!/usr/bin/env python3
"""
Pixel Paper – full-screen setup / status GUI
────────────────────────────────────────────
• Auto-scaling status text, portrait or landscape
• Smooth, stackable toast notifications
• Original BLE provisioning, Wi-Fi, kanshi rotation, repo-update intact
Colour palette: 010101 (bg), 1FC742, 025B18, 161616
"""
from __future__ import annotations
import os, socket, subprocess, threading, time, tkinter as tk
import tkinter.font as tkfont
from typing import List, Optional
from bluezero import adapter, peripheral
import launch                            # update_repo(), get_serial_number()

# ─── Brand colours ────────────────────────────────────────────────────────
CLR_BG      = "#010101"
CLR_ACCENT  = "#1FC742"
CLR_ACCENT2 = "#025B18"   # toast background
CLR_TEXT    = "#E8E8E8"

# ─── Toast system  (no overlap, smooth vertical glide) ───────────────────
class Toast:
    WIDTH       = 380
    PAD         = 12
    MARGIN_X    = 20
    MARGIN_Y    = 20
    SPACING_Y   = 10
    SLIDE_MS    = 250          # horizontal slide-in
    MOVE_MS     = 180          # vertical re-flow
    FADE_MS     = 400
    ALIVE_MS    = 4_000

    active: List["Toast"] = []

    def __init__(self, master: tk.Tk, text: str):
        self.master = master
        self.frame  = tk.Frame(master, bg=CLR_ACCENT2, highlightthickness=0)
        self.label  = tk.Label(self.frame, text=text, fg=CLR_TEXT, bg=CLR_ACCENT2,
                               justify="left", wraplength=self.WIDTH-2*self.PAD)
        self.label.pack(padx=self.PAD, pady=(self.PAD, self.PAD-2), anchor="w")
        self.frame.update_idletasks()
        self.h = self.frame.winfo_height()

        # pre-place off-screen to the right (anchor NE for edge alignment)
        x_start = self.WIDTH + self.MARGIN_X
        self.frame.place(relx=1.0, x=x_start, y=0, anchor="ne")

        # newest toast goes to top of stack
        Toast.active.insert(0, self)
        Toast._reflow(vertical_animate=False)  # instantly compute y targets

        # slide horizontally to final margin
        self._slide_in(x_start, -self.MARGIN_X)
        # schedule fade
        self.master.after(self.ALIVE_MS, self._fade_and_destroy)

    # ── animation helpers ────────────────────────────────────────────────
    def _slide_in(self, x_from: int, x_to: int):
        frames = max(1, int(self.SLIDE_MS/16))
        dx = (x_from - x_to) / frames
        def step(i=0):
            if i >= frames:
                self.frame.place_configure(x=x_to)
                return
            self.frame.place_configure(x=x_from - dx*i)
            self.master.after(16, step, i+1)
        step()

    def _move_to_y(self, y_final: int):
        start = self.frame.winfo_y()
        if abs(start - y_final) < 2:       # already there
            self.frame.place_configure(y=y_final)
            return
        frames = max(1, int(self.MOVE_MS/16))
        dy = (y_final - start) / frames
        def step(i=0):
            if i >= frames:
                self.frame.place_configure(y=y_final)
                return
            self.frame.place_configure(y=start + dy*i)
            self.master.after(16, step, i+1)
        step()

    def _fade_and_destroy(self):
        frames = max(1, int(self.FADE_MS/50))
        def fade(i=0):
            if i >= frames:
                self.frame.destroy()
                Toast.active.remove(self)
                Toast._reflow(vertical_animate=True)
                return
            t = 1 - i/frames
            self._set_alpha(t)
            self.master.after(50, fade, i+1)
        fade()

    def _set_alpha(self, alpha: float):
        def blend(c1,c2,t):
            a = int(c1[1:3],16); b = int(c2[1:3],16); r = int(a+(b-a)*t)
            a = int(c1[3:5],16); b = int(c2[3:5],16); g = int(a+(b-a)*t)
            a = int(c1[5:7],16); b = int(c2[5:7],16); b_ = int(a+(b-a)*t)
            return f"#{r:02x}{g:02x}{b_:02x}"
        new_bg = blend(CLR_ACCENT2, CLR_BG, 1-alpha)
        new_fg = blend(CLR_TEXT,    CLR_BG, 1-alpha)
        self.frame.configure(bg=new_bg)
        self.label.configure(bg=new_bg, fg=new_fg)

    # ── class-level layout ───────────────────────────────────────────────
    @classmethod
    def _reflow(cls, vertical_animate: bool):
        """Lay out all toasts (top-down)."""
        y = cls.MARGIN_Y
        for t in cls.active:
            if vertical_animate:
                t._move_to_y(y)
            else:
                t.frame.place_configure(y=y)
            y += t.h + cls.SPACING_Y

def log_debug(msg: str):
    print(msg)
    root.after(0, Toast, root, msg)

# ─── BLE UUIDs (unchanged) ───────────────────────────────────────────────
PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"
SERIAL_CHAR_UUID          = "12345678-1234-5678-1234-56789abcdef2"

# ─── Helper functions (Wi-Fi etc.) ───────────────────────────────────────
def get_serial_number() -> str:
    try:
        with open('/proc/device-tree/serial-number') as f:
            sn = f.read().strip('\x00\n ')
        return "PX"+sn
    except Exception:
        return "PXunknown"

def check_wifi_connection(retries=2) -> bool:
    for _ in range(retries):
        try:
            s=socket.create_connection(("8.8.8.8",53),timeout=2); s.close(); return True
        except OSError: time.sleep(0.25)
    return False

def nm_reconnect():
    try:
        ssid=subprocess.check_output(
            ["nmcli","-t","-f","NAME,TYPE,DEVICE,ACTIVE","connection","show","--active"],
            text=True).split(':')[0]
        subprocess.run(["nmcli","connection","up",ssid],check=False)
        log_debug(f"nmcli reconnect issued for {ssid}")
    except Exception as e: log_debug(f"nm_reconnect err: {e}")

# ─── Chromium watchdog ──────────────────────────────────────────────────
chromium_proc: Optional[subprocess.Popen]=None
repo_updated=False; fail_count=0; FAIL_MAX=3

def update_status():
    global chromium_proc, repo_updated, fail_count
    if check_wifi_connection():
        status_lbl.config(text="Connected ✓", fg=CLR_ACCENT)
        fail_count=0
        if not repo_updated:
            threading.Thread(target=launch.update_repo,daemon=True).start()
            repo_updated=True
        if chromium_proc is None or chromium_proc.poll() is not None:
            url=f"https://pixelpaper.com/frame.html?id={get_serial_number()}"
            subprocess.run(["pkill","-f","chromium"],check=False)
            chromium_proc=subprocess.Popen(["chromium","--kiosk",url])
            log_debug("Chromium launched.")
    else:
        fail_count+=1
        if fail_count>FAIL_MAX:
            status_lbl.config(text="Offline ⚠", fg="#ff9933")
            nm_reconnect()
        else:
            status_lbl.config(text="Waiting for Wi-Fi…", fg=CLR_TEXT)
    root.after(3_000, update_status)

# ─── BLE provisioning / rotation  (logic untouched, only log_debug) ─────
def handle_wifi_data(data:str):
    log_debug("Handling Wi-Fi data: "+data)
    try: ssid, pwd=data.split(';',1)[0], data.split('PASS:',1)[1]
    except Exception: log_debug("Payload malformed"); return
    try:
        for line in subprocess.check_output(
                ["nmcli","-t","-f","UUID,TYPE","connection","show"],text=True).splitlines():
            uuid,ctype=line.split(':',1)
            if ctype=="802-11-wireless":
                subprocess.run(["nmcli","connection","delete",uuid],
                               check=False,capture_output=True,text=True)
    except subprocess.CalledProcessError as e:
        log_debug(f"Profile list err: {e.stderr.strip()}")
    try:
        subprocess.run([
            "nmcli","connection","add","type","wifi","ifname","wlan0",
            "con-name",ssid,"ssid",ssid,
            "wifi-sec.key-mgmt","wpa-psk","wifi-sec.psk",pwd,
            "802-11-wireless-security.psk-flags","0",
            "connection.autoconnect","yes"
        ],check=True,capture_output=True,text=True)
        subprocess.run(["nmcli","connection","reload"],check=True)
        subprocess.run(["nmcli","connection","up",ssid],check=True,
                       capture_output=True,text=True)
        log_debug(f"Activated Wi-Fi '{ssid}'.")
    except subprocess.CalledProcessError as e:
        log_debug(f"nmcli error {e.returncode}: {e.stderr.strip() or e.stdout.strip()}")

def handle_orientation_change(data:str):
    out="HDMI-A-1"
    try:
        mode=subprocess.check_output(
            "wlr-randr | grep '(current)' | awk '{print $1\"@\"$3}'",
            shell=True,text=True).strip()
    except subprocess.CalledProcessError as e:
        log_debug(f"Mode detect fail: {e}"); return
    cfg=f"profile {{\n  output {out} enable mode {mode} position 0,0 transform {data}\n}}\n"
    path=os.path.expanduser("~/.config/kanshi/config")
    os.makedirs(os.path.dirname(path),exist_ok=True)
    with open(path,"w") as f:f.write(cfg)
    os.chmod(path,0o600)
    subprocess.run(["killall","kanshi"],check=False)
    subprocess.Popen(["kanshi","-c",path],
                     stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    log_debug(f"Rotated display → {data}°")

def ble_callback(val,opts):
    try:
        if val is None: return
        b=bytes(val) if isinstance(val,(list,bytes,bytearray)) else None
        if b is None: log_debug("Unexpected BLE type"); return
        msg=b.decode("utf-8","ignore").strip()
        log_debug("BLE: "+msg)
        if   msg.startswith("WIFI:"):   handle_wifi_data(msg[5:].strip())
        elif msg.startswith("ORIENT:"): handle_orientation_change(msg[7:].strip())
        elif msg=="REBOOT":             subprocess.run(["sudo","reboot"],check=False)
        else:                           log_debug("Unknown BLE cmd")
    except Exception as e: log_debug("ble_callback err: "+str(e))

def start_gatt_server():
    while True:
        try:
            adps=adapter.Adapter.available()
            if not adps: log_debug("No BT adapter"); time.sleep(4); continue
            p=peripheral.Peripheral(list(adps)[0].address, local_name="PixelPaper")
            p.add_service(1,PROVISIONING_SERVICE_UUID,True)
            p.add_characteristic(1,1,PROVISIONING_CHAR_UUID,value=[],
                                 notifying=False,flags=['write','write-without-response'],
                                 write_callback=ble_callback)
            p.add_characteristic(1,2,SERIAL_CHAR_UUID,
                                 value=list(get_serial_number().encode()),
                                 notifying=False,flags=['read'],
                                 read_callback=lambda _:
                                       list(get_serial_number().encode()))
            log_debug("GATT provisioning svc published")
            p.publish()
        except Exception as e: log_debug("GATT error: "+str(e))
        time.sleep(5)

def start_gatt_thread(): threading.Thread(target=start_gatt_server,daemon=True).start()

def disable_pairing():
    try:
        subprocess.run(["bluetoothctl"],input="pairable no\nquit\n",
                       text=True,capture_output=True,check=True)
    except Exception as e: log_debug("Disable pairing fail: "+str(e))

# ─── Tkinter full-screen UI ──────────────────────────────────────────────
root=tk.Tk(); root.title("Pixel Paper – Setup")
root.configure(bg=CLR_BG); root.attributes('-fullscreen',True)
root.bind("<Escape>",lambda e:None)

status_font=tkfont.Font(family="Helvetica",size=64,weight="bold")
status_lbl=tk.Label(root,text="Checking Wi-Fi…",fg=CLR_TEXT,bg=CLR_BG,font=status_font)
status_lbl.pack(expand=True)
root.bind("<Configure>",lambda e: status_font.configure(
    size=max(root.winfo_width(),root.winfo_height())//18))

# ─── Boot sequence ───────────────────────────────────────────────────────
disable_pairing()
start_gatt_thread()
root.after(200, update_status)
root.mainloop()
