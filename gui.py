import tkinter as tk
from ttkbootstrap import ttk
import socket
import subprocess
import time
import threading
import os
import queue

from bluezero import adapter, peripheral
import ttkbootstrap as tb
from ttkbootstrap.toast import ToastNotification

import launch

# ─────────────────────────── Globals & constants ────────────────────────────
launched            = False
debug_messages      = []
provisioning_char   = None
repo_updated        = False
FAIL_MAX            = 3
fail_count          = 0
chromium_process    = None

# BLE UUIDs
PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"
SERIAL_CHAR_UUID          = "12345678-1234-5678-1234-56789abcdef2"

# ──────────────────────── Thread-safe toast queue ───────────────────────────
toast_queue        = queue.SimpleQueue()
_toast_on_screen   = False


def _show_next_toast():
    """Pop one message off the queue and display it on the UI thread."""
    global _toast_on_screen
    if _toast_on_screen or toast_queue.empty():
        return

    _toast_on_screen = True
    message = toast_queue.get()

    # ── custom smoother toast (1.2 s fade-out instead of stock 0.25 s) ──
    class SmoothToast(ToastNotification):
        def hide_toast(self, *_):
            try:
                alpha = float(self.toplevel.attributes("-alpha"))
                if alpha <= 0.02:
                    self.toplevel.destroy()
                    _finish_toast()
                else:
                    self.toplevel.attributes("-alpha", alpha - 0.02)
                    self.toplevel.after(25, self.hide_toast)
            except Exception:
                self.toplevel.destroy()
                _finish_toast()

    def _finish_toast():
        global _toast_on_screen
        _toast_on_screen = False
        root.after_idle(_show_next_toast)

    SmoothToast(
        title="Pixel Paper",
        message=message,
        bootstyle="info",
        duration=3000,
        position=(10, 10, "ne"),
        alpha=0.95
    ).show_toast()


def log_debug(message: str):
    """Thread-safe debug logger that queues toast messages for the UI."""
    toast_queue.put(message)
    try:
        root.after_idle(_show_next_toast)
    except NameError:
        # root not yet created – only happens during initial import
        pass
    print(message)


# ───────────────────────────── Utilities ────────────────────────────────────
def get_serial_number() -> str:
    try:
        with open('/proc/device-tree/serial-number', 'r') as f:
            serial = f.read().strip('\x00\n ')
        return "PX" + serial
    except Exception:
        return "PXunknown"

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
            ["nmcli", "-t", "-f", "NAME,TYPE,DEVICE,ACTIVE",
             "connection", "show", "--active"],
            text=True
        ).split(':')[0]
        subprocess.run(["nmcli", "connection", "up", ssid], check=False)
        #log_debug(f"nmcli reconnect issued for {ssid}")
    except Exception as e:
        log_debug(f"Error: nm_reconnect: {e}")


def update_status():
    """Check Wi-Fi, relaunch Chromium if needed, update repo once online."""
    global chromium_process, fail_count, repo_updated
    try:
        up = check_wifi_connection()
        if up:
            if fail_count:
                fail_count = 0
                if not repo_updated:
                    threading.Thread(target=launch.update_repo,
                                     daemon=True).start()
                    repo_updated = True

            if chromium_process is None or chromium_process.poll() is not None:
                label.configure(text="Wi-Fi Connected")
                spinner.show()                             # ← show spinner
                threading.Thread(target=launch_chromium,      # ← launch in background
                                 daemon=True).start()
        else:
            fail_count += 1
            if fail_count > FAIL_MAX:
                label.configure(text="Wi-Fi Down…")
    except Exception as e:
        log_debug(f"Error: update_status: {e}")

def launch_chromium():
    """Kill old Chromium, start new kiosk, then hide the Tk window."""
    try:
        subprocess.run(["pkill", "-f", "chromium"], check=False)
        url = f"https://pixelpaper.com/frame.html?id={get_serial_number()}"
        proc = subprocess.Popen(["chromium", "--kiosk", url])
        time.sleep(2)                     # give Chromium a head-start
        root.after(0, spinner.hide)       # stop spinner
        root.after(0, root.withdraw)      # hide Tk window
    except Exception as e:
        log_debug(f"Error: launch_chromium: {e}")
        root.after(0, spinner.hide)


class BusySpinner:
    """Indeterminate Progressbar for background work."""
    def __init__(self, parent):
        self.pb = ttk.Progressbar(parent,
                                  mode="indeterminate",
                                  length=240,
                                  style="info-striped")
    def show(self):
        self.pb.place(relx=0.5, rely=0.6, anchor="center")
        self.pb.start(10)
        root.update_idletasks()
    def hide(self):
        self.pb.stop()
        self.pb.place_forget()


# ───────────────────────── BLE helper callbacks ─────────────────────────────
def handle_wifi_data(data: str):
    """
    Expects "MySSID;PASS:supersecret".
    Builds one NetworkManager keyfile profile with stored PSK so NM is silent.
    """
    #log_debug("Handling Wi-Fi data: " + data)
    try:
        ssid, pass_part = data.split(';', 1)
        password = pass_part.split(':', 1)[1]
    except ValueError:
        log_debug("Wi-Fi payload malformed; expected SSID;PASS:pwd")
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
        log_debug(f"Error: Could not list profiles: {e.stderr.strip()}")

    try:
        subprocess.run([
            "nmcli", "connection", "add",
            "type",      "wifi",
            "ifname",    "wlan0",
            "con-name",  ssid,
            "ssid",      ssid,
            "wifi-sec.key-mgmt", "wpa-psk",
            "wifi-sec.psk",      password,
            "802-11-wireless-security.psk-flags", "0",
            "connection.autoconnect", "yes"
        ], check=True, capture_output=True, text=True)

        subprocess.run(["nmcli", "connection", "reload"], check=True)
        subprocess.run(["nmcli", "connection", "up", ssid],
                       check=True, capture_output=True, text=True)

        log_debug(f"Connected to: '{ssid}'")
    except subprocess.CalledProcessError as e:
        log_debug(f"nmcli error {e.returncode}: {e.stderr.strip() or e.stdout.strip()}")

def handle_orientation_change(data: str):
    """
    data in {"normal","90","180","270"}:
      1) detect current mode@freq via wlr-randr
      2) write ~/.config/kanshi/config
      3) restart kanshi
    """
    output = "HDMI-A-1"
    try:
        mode = subprocess.check_output(
            "wlr-randr | grep '(current)' | awk '{print $1\"@\"$3}'",
            shell=True, text=True
        ).strip()
    except subprocess.CalledProcessError as e:
        log_debug(f"Error: Failed to detect current mode: {e}")
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
    #log_debug(f"Wrote kanshi config: mode={mode}, transform={data}")

    subprocess.run(["killall", "kanshi"], check=False)
    subprocess.Popen(["kanshi", "-c", cfg_path],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    orientation = "Portrait" if data in ["90", "270"] else "Landscape"
    log_debug(f"{orientation}")

def ble_callback(value, options):
    try:
        if value is None:
            return
        value_bytes = bytes(value) if isinstance(value, list) else value
        message = value_bytes.decode("utf-8", errors="ignore").strip()
        #log_debug("Received BLE data: " + message)

        if message.startswith("WIFI:"):
            handle_wifi_data(message[len("WIFI:"):].strip())
        elif message.startswith("ORIENT:"):
            handle_orientation_change(message[len("ORIENT:"):].strip())
        elif message == "REBOOT":
            log_debug("Restarting...")
            subprocess.run(["sudo", "reboot"], check=False)
        else:
            log_debug("Error: Unknown BLE command received.")
    except Exception as e:
        log_debug("Error: ble_callback: " + str(e))


# ───────────────────────────── BLE server ───────────────────────────────────
def start_gatt_server():
    global provisioning_char
    while True:
        try:
            dongles = adapter.Adapter.available()
            if not dongles:
                log_debug("Error: No Bluetooth adapters available!")
                time.sleep(5)
                continue

            dongle_addr = list(dongles)[0].address
            #log_debug("Using Bluetooth adapter for GATT server: " + dongle_addr)

            ble_periph = peripheral.Peripheral(dongle_addr, local_name="PixelPaper")
            ble_periph.add_service(1, PROVISIONING_SERVICE_UUID, primary=True)

            provisioning_char = ble_periph.add_characteristic(
                1, 1, PROVISIONING_CHAR_UUID,
                value=[], notifying=False,
                flags=['write', 'write-without-response'],
                write_callback=ble_callback
            )
            ble_periph.add_characteristic(
                1, 2, SERIAL_CHAR_UUID,
                value=list(get_serial_number().encode()),
                notifying=False, flags=['read'],
                read_callback=lambda options: list(get_serial_number().encode())
            )

            #log_debug("Publishing GATT server for provisioning and serial...")
            ble_periph.publish()
            #log_debug("GATT server event loop ended.")
        except Exception as e:
            log_debug("Error: Exception in start_gatt_server: " + str(e))
        log_debug("Error: Restarting GATT server in 5 seconds...")
        time.sleep(5)


def start_gatt_server_thread():
    threading.Thread(target=start_gatt_server, daemon=True).start()

# ─────────────────────────────── Main GUI ───────────────────────────────────
if __name__ == '__main__':
     root = tb.Window(themename="litera")
     GREEN = "#1FC742"
     root.style.colors.set('info', GREEN)
     root.style.configure("TFrame", background="black")
     root.style.configure("TLabel", background="black", foreground=GREEN)
     root.configure(background="black")

     root.title("Frame Status")
     root.attributes('-fullscreen', True)
     root.bind('<Escape>', lambda e: root.attributes('-fullscreen', False))
     root.bind("<<ToastHidden>>", lambda *_: root.attributes('-fullscreen', True))

     # define a custom ttk style for status text
     root.style.configure("Status.TLabel",
                          background="black",
                          foreground=GREEN,
                          font=("Helvetica", 48))
     label = ttk.Label(
         root,
         text="Checking Wi-Fi…",
         style="Status.TLabel"
     )
     label.pack(expand=True)

     disable_pairing()
     start_gatt_server_thread()
     update_status()

     # create spinner after root exists
     spinner = BusySpinner(root)

     # lightweight heartbeat: poll every 2s
     def heartbeat():
         update_status()
         root.after(2000, heartbeat)
     heartbeat()

     root.mainloop()