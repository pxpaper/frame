#!/usr/bin/env python3
"""
gui.py – Pixel Paper frame GUI & BLE provisioning
• Centered loading.gif spinner (2× speed) while Chromium launches
• BLE  CLEAR_WIFI  wipes all saved Wi-Fi profiles
• Label now shows:
      – “Waiting for Wi-Fi…” when no connection
      – “Wi-Fi Connected” + spinner while Chromium starts
"""
import os, queue, socket, subprocess, threading, time, tkinter as tk
from itertools import count
from bluezero import adapter, peripheral
import ttkbootstrap as tb
from ttkbootstrap.toast import ToastNotification
from ttkbootstrap import ttk

# ── paths ──────────────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
SPINNER_GIF = os.path.join(SCRIPT_DIR, "loading.gif")

# ── constants / globals ────────────────────────────────────────────────
GREEN = "#1FC742"
chromium_process = None
provisioning_char = None

UUID_SVC = "12345678-1234-5678-1234-56789abcdef0"
UUID_WIFI= "12345678-1234-5678-1234-56789abcdef1"
UUID_SN  = "12345678-1234-5678-1234-56789abcdef2"

toast_queue, _toast_on_screen = queue.SimpleQueue(), False

# ───────────────────────────── Toasts ──────────────────────────────────
def _show_toast():
    global _toast_on_screen
    if _toast_on_screen or toast_queue.empty(): return
    _toast_on_screen = True
    msg = toast_queue.get()
    class Smooth(ToastNotification):
        def hide_toast(self,*_):
            try:
                a=float(self.toplevel.attributes('-alpha'))
                if a<=.02:self.toplevel.destroy();reset()
                else:self.toplevel.attributes('-alpha',a-.02);self.toplevel.after(25,self.hide_toast)
            except: self.toplevel.destroy();reset()
    def reset():
        global _toast_on_screen; _toast_on_screen=False; root.after_idle(_show_toast)
    Smooth(title="Pixel Paper", message=msg, bootstyle="info",
           duration=3000, position=(10,10,"ne"), alpha=.95).show_toast()

def log_debug(m): toast_queue.put(m); print(m,flush=True)

# ─────────────────────────── Spinner ───────────────────────────────────
spinner_frames, spinner_running, SPIN_DELAY = [], False, 40
def load_spinner():
    if not os.path.exists(SPINNER_GIF): return
    for i in count():
        try: spinner_frames.append(tk.PhotoImage(file=SPINNER_GIF,format=f"gif -index {i}"))
        except tk.TclError: break
def animate(idx=0):
    if not spinner_running or not spinner_frames: return
    spinner_label.configure(image=spinner_frames[idx])
    root.after(SPIN_DELAY, animate, (idx+1)%len(spinner_frames))
def show_spinner():
    global spinner_running
    if spinner_running or not spinner_frames: return
    spinner_label.pack(pady=(12,0)); spinner_running=True; animate()
def hide_spinner():
    global spinner_running
    if spinner_running: spinner_label.pack_forget(); spinner_running=False

# ───────────────────────── Utilities ───────────────────────────────────
def get_serial():
    try:
        with open('/proc/device-tree/serial-number') as f:
            return "PX"+f.read().strip('\x00\n ')
    except: return "PXunknown"
def disable_pairing():
    subprocess.run(["bluetoothctl"],input="pairable no\nquit\n",
                   text=True,capture_output=True)
def ping_google()->bool:
    try:
        s=socket.create_connection(("8.8.8.8",53),timeout=3); s.close(); return True
    except OSError: return False
def clear_wifi():
    try:
        profiles=subprocess.check_output(
            ["nmcli","-t","-f","UUID,TYPE","connection","show"],text=True).splitlines()
        for l in profiles:
            uuid,typ=l.split(':',1)
            if typ=="802-11-wireless":
                subprocess.run(["nmcli","connection","delete",uuid],check=False)
        subprocess.run(["nmcli","connection","reload"],check=False)
        subprocess.run(["nmcli","networking","off"],check=False)
        subprocess.run(["nmcli","networking","on"],check=False)
        log_debug("Wi-Fi profiles cleared")
    except Exception as e: log_debug(f"clear_wifi: {e}")

# ─────────────────── Wi-Fi / Chromium loop ─────────────────────────────
def poll_wifi():
    global chromium_process
    if ping_google():
        if chromium_process is None or chromium_process.poll() is not None:
            status.configure(text="Wi-Fi Connected")
            show_spinner()
            subprocess.run(["pkill","-f","chromium"],check=False)
            url=f"https://pixelpaper.com/frame.html?id={get_serial()}"
            chromium_process=subprocess.Popen(["chromium","--kiosk",url])
    else:
        hide_spinner()
        status.configure(text="Waiting for Wi-Fi…")
    root.after(5000,poll_wifi)

# ───────────────── BLE callback & server ───────────────────────────────
def wifi_payload(payload:str):
    try: ssid,pwd=payload.split(';PASS:')
    except ValueError: log_debug("Bad WIFI payload"); return
    clear_wifi()
    subprocess.run(["nmcli","connection","add","type","wifi","ifname","wlan0",
                    "con-name",ssid,"ssid",ssid,
                    "wifi-sec.key-mgmt","wpa-psk","wifi-sec.psk",pwd,
                    "802-11-wireless-security.psk-flags","0",
                    "connection.autoconnect","yes"],check=False)
    subprocess.run(["nmcli","connection","up",ssid],check=False)
def orient_payload(d): handle_orientation_change(d)   # reuse existing func

def ble_cb(value,_):
    if value is None: return
    msg=(bytes(value) if isinstance(value,list) else value).decode("utf-8","ignore").strip()
    if   msg.startswith("WIFI:"):   wifi_payload(msg[5:].strip())
    elif msg.startswith("ORIENT:"): orient_payload(msg[7:].strip())
    elif msg=="CLEAR_WIFI":         clear_wifi(); hide_spinner(); status.configure(text="Waiting for Wi-Fi…"); subprocess.run(["pkill","-f","chromium"],check=False)
    elif msg=="REBOOT":             log_debug("Restarting…"); subprocess.run(["sudo","reboot"],check=False)
    else: log_debug("Unknown BLE cmd")

def start_ble():
    while True:
        try:
            dongle=list(adapter.Adapter.available())[0].address
            p=peripheral.Peripheral(dongle,local_name="PixelPaper")
            p.add_service(1,UUID_SVC,primary=True)
            p.add_characteristic(1,1,UUID_WIFI,value=[],notifying=False,
                                 flags=['write','write-without-response'],
                                 write_callback=ble_cb)
            p.add_characteristic(1,2,UUID_SN,value=list(get_serial().encode()),
                                 notifying=False,flags=['read'],
                                 read_callback=lambda _o:list(get_serial().encode()))
            p.publish()
        except Exception as e: log_debug(f"GATT error: {e}")
        time.sleep(5)

# ───────────────────────────── Build GUI ───────────────────────────────
root=tb.Window(themename="litera")
root.style.colors.set("info",GREEN)
root.style.configure("TFrame",background="black")
root.style.configure("Status.TLabel",background="black",
                     foreground=GREEN,font=("Helvetica",48))
root.configure(bg="black")
root.title("Frame Status")
root.attributes('-fullscreen',True)
root.bind('<Escape>',lambda e:root.attributes('-fullscreen',False))
root.after_idle(_show_toast)

center=ttk.Frame(root,style="TFrame"); center.pack(expand=True)
status=ttk.Label(center,text="Waiting for Wi-Fi…",style="Status.TLabel"); status.pack()
load_spinner()
spinner_label=tk.Label(center,bg="black",bd=0,highlightthickness=0)

disable_pairing()
threading.Thread(target=start_ble,daemon=True).start()
poll_wifi()
root.mainloop()
