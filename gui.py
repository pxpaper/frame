#!/usr/bin/env python3
"""
Pixel Paper – full-screen status & provisioning GUI
───────────────────────────────────────────────────
• Launches from launch.py, runs before Chromium
• Auto-scaling portrait/landscape design
• Brand colours: 010101 | 1FC742 | 025B18 | 161616
• Smooth ToastNotification pop-ups via ttkbootstrap
• BLE GATT server identical to original (now calls .run())
Prerequisite:
    pip install --upgrade ttkbootstrap bluezero
"""
from __future__ import annotations
import os, socket, subprocess, threading, time
import tkinter.font as tkfont
from typing import List, Optional

# ── third-party ───────────────────────────────────────────────────────────
import ttkbootstrap as ttk
from ttkbootstrap.toast import ToastNotification
from bluezero import adapter, peripheral

# ── project helpers ───────────────────────────────────────────────────────
import launch            # update_repo() + get_serial_number()

# ── palette ───────────────────────────────────────────────────────────────
CLR_BG     = "#010101"
CLR_ACCENT = "#1FC742"
CLR_TEXT   = "#E8E8E8"

# ── Toast helpers ─────────────────────────────────────────────────────────
_TOASTS: List[ToastNotification] = []
STACK_STEP = 70           # px between stacked toasts

def _show_toast(msg: str, style: str = "success"):
    y = 20 + len(_TOASTS) * STACK_STEP
    toast = ToastNotification(
        title="Pixel Paper", message=msg,
        duration=3500, bootstyle=style, position=(20, y, "ne")
    )
    _TOASTS.append(toast)
    toast.show_toast()
    def purge(): _TOASTS.remove(toast) if toast in _TOASTS else None
    root.after(3700, purge)

def log_debug(msg: str):
    print(msg)
    root.after(0, _show_toast, msg)

# ── BLE UUIDs (unchanged) ─────────────────────────────────────────────────
PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"
SERIAL_CHAR_UUID          = "12345678-1234-5678-1234-56789abcdef2"

# ── Wi-Fi utilities ───────────────────────────────────────────────────────
def check_wifi_connection(retries=2) -> bool:
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
            ["nmcli", "-t", "-f", "NAME,TYPE,DEVICE,ACTIVE",
             "connection", "show", "--active"], text=True
        ).split(':')[0]
        subprocess.run(["nmcli", "connection", "up", ssid], check=False)
        log_debug(f"nmcli reconnect issued for {ssid}")
    except Exception as e:
        log_debug(f"nm_reconnect err: {e}")

# ── Chromium watchdog ────────────────────────────────────────────────────
chromium_proc: Optional[subprocess.Popen] = None
repo_updated  = False
fail_count    = 0
FAIL_MAX      = 3

def update_status():
    global chromium_proc, repo_updated, fail_count
    online = check_wifi_connection()

    if online:
        status_lbl.configure(text="Connected ✓", foreground=CLR_ACCENT)
        fail_count = 0
        if not repo_updated:
            threading.Thread(target=launch.update_repo, daemon=True).start()
            repo_updated = True
        if chromium_proc is None or chromium_proc.poll() is not None:
            url = f"https://pixelpaper.com/frame.html?id={launch.get_serial_number()}"
            subprocess.run(["pkill", "-f", "chromium"], check=False)
            chromium_proc = subprocess.Popen(["chromium", "--kiosk", url])
            log_debug("Chromium launched for frame display.")
    else:
        if fail_count < FAIL_MAX:
            fail_count += 1
            status_lbl.configure(text="Waiting for Wi-Fi…", foreground=CLR_TEXT)
        else:
            status_lbl.configure(text="Offline ⚠", foreground="#ff9933")
            nm_reconnect()

    root.after(3_000, update_status)

# ── Wi-Fi provisioning & orientation – original logic unchanged ──────────
def handle_wifi_data(data: str):
    log_debug("Handling Wi-Fi data: " + data)
    try:  ssid, pass_part = data.split(';',1); password = pass_part.split(':',1)[1]
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
            "nmcli","connection","add","type","wifi","ifname","wlan0",
            "con-name",ssid,"ssid",ssid,
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
        log_debug(f"Failed to detect current mode: {e}"); return
    cfg = f"profile {{\n  output {output} enable mode {mode} position 0,0 transform {data}\n}}\n"
    cfg_path = os.path.expanduser("~/.config/kanshi/config")
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    with open(cfg_path,"w") as f: f.write(cfg)
    os.chmod(cfg_path,0o600)
    subprocess.run(["killall","kanshi"],check=False)
    subprocess.Popen(["kanshi","-c",cfg_path],
                     stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    log_debug(f"Rotated display → {data}°")

def ble_callback(value, options):
    try:
        if value is None: return
        vb = (bytes(value) if isinstance(value, list)
              else bytes(value) if isinstance(value,(bytes,bytearray)) else None)
        if vb is None: log_debug(f"Unexpected BLE value type: {type(value)}"); return
        msg = vb.decode("utf-8",errors="ignore").strip()
        log_debug("Received BLE data: " + msg)
        if   msg.startswith("WIFI:"):   handle_wifi_data(msg[5:].strip())
        elif msg.startswith("ORIENT:"): handle_orientation_change(msg[7:].strip())
        elif msg == "REBOOT":           subprocess.run(["sudo","reboot"],check=False)
        else:                           log_debug("Unknown BLE command.")
    except Exception as e:
        log_debug("Error in ble_callback: " + str(e))

# ── GATT server (identical API, now with .run()) ─────────────────────────
def gatt_server():
    while True:
        try:
            dongles = adapter.Adapter.available()
            if not dongles:
                log_debug("No Bluetooth adapters available for GATT!"); time.sleep(5); continue
            addr = list(dongles)[0].address
            log_debug("Using Bluetooth adapter: " + addr)

            periph = peripheral.Peripheral(addr, local_name="PixelPaper")
            periph.add_service(1, PROVISIONING_SERVICE_UUID, primary=True)

            periph.add_characteristic(
                1, 1, PROVISIONING_CHAR_UUID,
                value=[], notifying=False,
                flags=['write','write-without-response'],
                write_callback=ble_callback
            )
            periph.add_characteristic(
                1, 2, SERIAL_CHAR_UUID,
                value=list(launch.get_serial_number().encode()),
                notifying=False, flags=['read'],
                read_callback=lambda _:
                    list(launch.get_serial_number().encode())
            )
            log_debug("Publishing GATT provisioning service…")
            periph.publish()
            periph.run()   # <-- keeps the GLib main-loop alive
            log_debug("GATT loop ended (disconnect).")
        except Exception as e:
            log_debug(f"GATT error: {e}")
        log_debug("Restarting GATT server in 5 s…"); time.sleep(5)

def start_gatt_thread(): threading.Thread(target=gatt_server, daemon=True).start()

def disable_pairing():
    try:
        subprocess.run(["bluetoothctl"],
                       input="pairable no\nquit\n",
                       text=True,capture_output=True,check=True)
    except Exception as e:
        log_debug("Failed to disable pairing: " + str(e))

# ── ttkbootstrap full-screen UI ──────────────────────────────────────────
root = ttk.Window(themename="darkly")
root.title("Pixel Paper – Setup")
root.configure(bg=CLR_BG)
root.attributes('-fullscreen', True)
root.bind("<Escape>", lambda e: None)

status_font = tkfont.Font(family="Helvetica", size=64, weight="bold")
status_lbl  = ttk.Label(root, text="Checking Wi-Fi…",
                        foreground=CLR_TEXT, background=CLR_BG,
                        font=status_font)
status_lbl.pack(expand=True)

def _autoscale(event=None):
    status_font.configure(size=max(root.winfo_width(),root.winfo_height())//18)
root.bind("<Configure>", _autoscale)

# ── boot sequence ────────────────────────────────────────────────────────
disable_pairing()
start_gatt_thread()
root.after(200, update_status)
root.mainloop()
