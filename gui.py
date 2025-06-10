#!/usr/bin/env python3
# gui.py – Pixel Paper frame UI (ttkbootstrap edition)
# ---------------------------------------------------------------------------
# • All I/O logic from the original script is preserved.
# • Only presentation has changed (full-screen Tk/ttkbootstrap + toast logs).
# ---------------------------------------------------------------------------
import tkinter as tk
import socket, subprocess, time, threading, os, sys
from functools import partial

# --- third-party UI helpers ------------------------------------------------
try:
    import ttkbootstrap as tb
    from ttkbootstrap.toast import ToastNotification
except ModuleNotFoundError:
    print(
        "⚠️  ttkbootstrap not found – run  pip install ttkbootstrap  "
        "inside your venv.",
        file=sys.stderr,
    )
    sys.exit(1)

# Import repo-update helper from launch.py (same directory)
import launch

# ---------------------------------------------------------------------------
# •••  BRAND COLOURS + STYLE  •••
# ---------------------------------------------------------------------------
BRAND_BG      = "#010101"
BRAND_SUCCESS = "#1FC742"
BRAND_DGREE   = "#025B18"
BRAND_DARK    = "#161616"

# create the bootstrap window with a dark theme & custom colors
style = tb.Style("darkly")
# tweak a couple of palette slots so built-in “success”/etc. match our greens
style.colors.update(
    {
        "success": BRAND_SUCCESS,
        "selectbg": BRAND_SUCCESS,
        "selectfg": "#ffffff",
        "secondary": BRAND_DGREE,
    }
)

root: tb.Window = tb.Window(themename="darkly")
root.configure(background=BRAND_BG)
root.attributes("-fullscreen", True)
root.title("Pixel Paper – Frame Status")

# ---------------------------------------------------------------------------
#  UI ELEMENTS
# ---------------------------------------------------------------------------
_status_var = tk.StringVar(value="Checking Wi-Fi…")

# Big centred status label (font auto-scales to window size)
status_lbl = tb.Label(
    root,
    textvariable=_status_var,
    font=("Helvetica Neue", 56, "bold"),
    bootstyle="success",
    background=BRAND_BG,
    anchor="center",
)
status_lbl.pack(expand=True, fill="both")


def _rescale_font(event):
    """Dynamically adjust font size ~7% of the shorter screen edge."""
    size = int(min(event.width, event.height) * 0.07)
    status_lbl.configure(font=("Helvetica Neue", size, "bold"))


root.bind("<Configure>", _rescale_font)

# ---------------------------------------------------------------------------
#  LOGGING → toast notifications
# ---------------------------------------------------------------------------
_TOAST_LIFETIME_MS = 5000
_toast_stack_off   = 10  # px gap between toasts
_active_toasts     = []  # keep refs to stack them vertically


def _show_toast(msg: str, kind: str = "secondary"):
    """Display a stackable toast in the top-right corner."""
    toast = ToastNotification(
        title="Pixel Paper",
        message=msg,
        duration=_TOAST_LIFETIME_MS,
        alert=False,
        bootstyle=kind,
        position=(0.98, 0.02),  # anchored top-right in screen coords
        master=root,
    )
    # Shift older toasts downward
    for t in _active_toasts:
        x, y = t.window.winfo_x(), t.window.winfo_y()
        t.window.geometry(f"+{x}+{y + t.window.winfo_height() + _toast_stack_off}")
    _active_toasts.insert(0, toast)
    toast.show()

    # Purge ref when toast disappears
    root.after(
        _TOAST_LIFETIME_MS + 100,
        lambda: _active_toasts.remove(toast) if toast in _active_toasts else None,
    )


def log_debug(message):
    print(message)        # still echo to stdout for journald
    _show_toast(message, "secondary")


# ---------------------------------------------------------------------------
#  BLE / Wi-Fi / orientation logic – UNCHANGED from original
#  (only trimmed comments to save space)
# ---------------------------------------------------------------------------
from bluezero import adapter, peripheral

launched = False
provisioning_char = None
repo_updated = False

PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"
SERIAL_CHAR_UUID          = "12345678-1234-5678-1234-56789abcdef2"

FAIL_MAX   = 3
fail_count = 0
chromium_process = None


def get_serial_number():
    try:
        with open("/proc/device-tree/serial-number", "r") as f:
            serial = f.read().strip("\x00\n ")
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
            check=True,
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
        ssid = (
            subprocess.check_output(
                [
                    "nmcli",
                    "-t",
                    "-f",
                    "NAME,TYPE,DEVICE,ACTIVE",
                    "connection",
                    "show",
                    "--active",
                ],
                text=True,
            )
            .split(":")[0]
        )
        subprocess.run(["nmcli", "connection", "up", ssid], check=False)
        log_debug(f"nmcli reconnect issued for {ssid}")
    except Exception as e:
        log_debug(f"nm_reconnect err: {e}")


def update_status():
    global chromium_process, fail_count, repo_updated

    try:
        up = check_wifi_connection()
        if up:
            _status_var.set("Wi-Fi ✓  – launching frame")
            status_lbl.configure(bootstyle="success")

            # was offline → now online
            if fail_count:
                fail_count = 0
                if not repo_updated:
                    threading.Thread(target=launch.update_repo, daemon=True).start()
                    repo_updated = True

            # (re)start Chromium if needed
            if chromium_process is None or chromium_process.poll() is not None:
                subprocess.run(["pkill", "-f", "chromium"], check=False)
                url = f"https://pixelpaper.com/frame.html?id={get_serial_number()}"
                chromium_process = subprocess.Popen(["chromium", "--kiosk", url])
        else:
            fail_count += 1
            _status_var.set("Wi-Fi disconnected")
            status_lbl.configure(bootstyle="danger")
            if fail_count > FAIL_MAX:
                nm_reconnect()
                fail_count = 0
    except Exception as e:
        log_debug(f"update_status error: {e}")

    # schedule next check
    root.after(3000, update_status)


# ---------------------------------------------------------------------------
#  Wi-Fi provisioning helpers (unchanged save for log_debug)
# ---------------------------------------------------------------------------
def handle_wifi_data(data: str):
    log_debug("Handling WiFi data: " + data)
    try:
        ssid, pass_part = data.split(";", 1)
        password = pass_part.split(":", 1)[1]
    except ValueError:
        log_debug("WiFi payload malformed; expected SSID;PASS:pwd")
        return

    # wipe existing Wi-Fi profiles
    try:
        profiles = subprocess.check_output(
            ["nmcli", "-t", "-f", "UUID,TYPE", "connection", "show"], text=True
        ).splitlines()
        for line in profiles:
            uuid, ctype = line.split(":", 1)
            if ctype == "802-11-wireless":
                subprocess.run(
                    ["nmcli", "connection", "delete", uuid],
                    check=False,
                    capture_output=True,
                    text=True,
                )
    except subprocess.CalledProcessError as e:
        log_debug(f"Could not list profiles: {e.stderr.strip()}")

    # add keyfile profile with stored PSK
    try:
        subprocess.run(
            [
                "nmcli",
                "connection",
                "add",
                "type",
                "wifi",
                "ifname",
                "wlan0",
                "con-name",
                ssid,
                "ssid",
                ssid,
                "wifi-sec.key-mgmt",
                "wpa-psk",
                "wifi-sec.psk",
                password,
                "802-11-wireless-security.psk-flags",
                "0",
                "connection.autoconnect",
                "yes",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(["nmcli", "connection", "reload"], check=True)
        subprocess.run(["nmcli", "connection", "up", ssid], check=True)
        log_debug(f"Activated Wi-Fi connection '{ssid}' non-interactively.")
    except subprocess.CalledProcessError as e:
        log_debug(
            f"nmcli error {e.returncode}: {e.stderr.strip() or e.stdout.strip()}"
        )


def handle_orientation_change(data):
    output = "HDMI-A-1"
    try:
        mode = subprocess.check_output(
            "wlr-randr | grep '(current)' | awk '{print $1\"@\"$3}'",
            shell=True,
            text=True,
        ).strip()
    except subprocess.CalledProcessError as e:
        log_debug(f"Failed to detect current mode: {e}")
        return
    cfg = f"""profile {{
    output {output} enable mode {mode} position 0,0 transform {data}
}}"""
    cfg_path = os.path.expanduser("~/.config/kanshi/config")
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    with open(cfg_path, "w") as f:
        f.write(cfg)
    os.chmod(cfg_path, 0o600)
    subprocess.run(["killall", "kanshi"], check=False)
    subprocess.Popen(
        ["kanshi", "-c", cfg_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    log_debug(f"Rotated {output} → {data}° via kanshi")


def ble_callback(value, options):
    try:
        if value is None:
            return
        value_bytes = (
            bytes(value)
            if isinstance(value, list)
            else value
            if isinstance(value, (bytes, bytearray))
            else None
        )
        if value_bytes is None:
            log_debug(f"Unexpected BLE value type: {type(value)}")
            return
        message = value_bytes.decode("utf-8", errors="ignore").strip()
        log_debug("Received BLE data: " + message)

        if message.startswith("WIFI:"):
            handle_wifi_data(message[len("WIFI:") :].strip())
        elif message.startswith("ORIENT:"):
            handle_orientation_change(message[len("ORIENT:") :].strip())
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
            log_debug("Using Bluetooth adapter for GATT server: " + dongle_addr)

            ble_periph = peripheral.Peripheral(dongle_addr, local_name="PixelPaper")
            ble_periph.add_service(
                srv_id=1, uuid=PROVISIONING_SERVICE_UUID, primary=True
            )
            provisioning_char = ble_periph.add_characteristic(
                srv_id=1,
                chr_id=1,
                uuid=PROVISIONING_CHAR_UUID,
                value=[],
                notifying=False,
                flags=["write", "write-without-response"],
                write_callback=ble_callback,
            )
            ble_periph.add_characteristic(
                srv_id=1,
                chr_id=2,
                uuid=SERIAL_CHAR_UUID,
                value=list(get_serial_number().encode()),
                notifying=False,
                flags=["read"],
                read_callback=lambda options: list(get_serial_number().encode()),
            )
            log_debug("Publishing GATT server for provisioning and serial...")
            ble_periph.publish()
            log_debug("GATT server event loop ended.")
        except Exception as e:
            log_debug("Exception in start_gatt_server: " + str(e))
        log_debug("Restarting GATT server in 5 s…")
        time.sleep(5)


def start_gatt_server_thread():
    threading.Thread(target=start_gatt_server, daemon=True).start()


# ---------------------------------------------------------------------------
#  MAIN – initialise services & kick off periodic status checks
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    disable_pairing()
    start_gatt_server_thread()
    update_status()  # kicks off repeating after() chain
    root.mainloop()
