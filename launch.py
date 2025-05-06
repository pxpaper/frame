#!/usr/bin/env python3
import tkinter as tk
import socket
import subprocess
import time
import threading
import os
from pathlib import Path
from bluezero import adapter, peripheral

# ────────────────────────────────────────────────────────────────────────────
# Constants & globals
# ────────────────────────────────────────────────────────────────────────────
FAIL_MAX          = 3          # misses before we declare offline
chromium_cmd      = ["chromium", "--kiosk",
                     "https://pixelpaper.com/frame.html?id=frame1"]

launched          = False
debug_messages    = []
provisioning_char = None
chromium_process  = None
fail_count        = 0
repo_updated      = False        # ← new: ensure we pull only once per run

# UUIDs for custom provisioning service and characteristics
PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"
SERIAL_CHAR_UUID          = "12345678-1234-5678-1234-56789abcdef2"


# ────────────────────────────────────────────────────────────────────────────
# Utility helpers
# ────────────────────────────────────────────────────────────────────────────
def get_serial_number() -> str:
    try:
        with open('/proc/device-tree/serial-number', 'r') as f:
            serial = f.read().strip('\x00\n ')
        return "PX" + serial
    except Exception:
        return "PXunknown"


def log_debug(message: str) -> None:
    global debug_text
    debug_messages.append(message)
    # keep only last 10 lines
    debug_text.config(state=tk.NORMAL)
    debug_text.delete(1.0, tk.END)
    debug_text.insert(tk.END, "\n".join(debug_messages[-10:]))
    debug_text.config(state=tk.DISABLED)
    print(message)


def disable_pairing() -> None:
    try:
        subprocess.run(
            ["bluetoothctl"],
            input="pairable no\nquit\n",
            text=True,
            capture_output=True,
            check=True
        )
    except Exception as exc:
        log_debug(f"Failed to disable pairing: {exc}")


def check_wifi_connection(retries: int = 2) -> bool:
    """Ping 8.8.8.8:53 via TCP to test real connectivity."""
    for _ in range(retries):
        try:
            s = socket.create_connection(("8.8.8.8", 53), timeout=3)
            s.close()
            return True
        except OSError:
            time.sleep(0.3)
    return False


# ────────────────────────────────────────────────────────────────────────────
# Git updater (optional background pull once Wi‑Fi resurfaces)
# ────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent

def update_repo() -> None:
    """Same hard‑reset logic as launch.py (duplicated for self‑containment)."""
    try:
        subprocess.run(
            ["git", "fetch", "--all", "--prune"],
            cwd=SCRIPT_DIR,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["git", "reset", "--hard", "origin/main"],
            cwd=SCRIPT_DIR,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log_debug("Repo auto‑updated after Wi‑Fi recovery.")
    except Exception as exc:
        log_debug(f"Repo update failed: {exc}")


def nm_reconnect() -> None:
    """Bounce the currently active connection to force a retry."""
    try:
        ssid = subprocess.check_output(
            ["nmcli", "-t", "-f", "NAME,TYPE,DEVICE,ACTIVE",
             "connection", "show", "--active"],
            text=True
        ).split(':')[0]
        subprocess.run(["nmcli", "connection", "up", ssid], check=False)
        log_debug(f"nmcli reconnect issued for {ssid}")
    except Exception as exc:
        log_debug(f"nm_reconnect err: {exc}")


# ────────────────────────────────────────────────────────────────────────────
# Main connectivity loop
# ────────────────────────────────────────────────────────────────────────────
def update_status() -> None:
    """Runs every 10 s, manages Chromium and (optionally) repo updates."""
    global chromium_process, fail_count, repo_updated

    try:
        up = check_wifi_connection()
        if up:
            if fail_count != 0 and not repo_updated:
                # just transitioned from offline → online
                threading.Thread(target=update_repo, daemon=True).start()
                repo_updated = True

            fail_count = 0
            if chromium_process is None or chromium_process.poll() is not None:
                label.config(text="Wi‑Fi OK → starting frame")
                subprocess.run(["pkill", "-f", "chromium"], check=False)
                chromium_process = subprocess.Popen(chromium_cmd)
        else:
            fail_count += 1
            if fail_count == FAIL_MAX:
                label.config(text="Wi‑Fi lost → reconnecting…")
                nm_reconnect()
            if fail_count >= FAIL_MAX * 2:
                label.config(text="Wi‑Fi lost → closing frame")
                if chromium_process and chromium_process.poll() is None:
                    subprocess.run(["pkill", "-f", "chromium"], check=False)
                    chromium_process = None
    except Exception as exc:
        log_debug(f"update_status err: {exc}")
    finally:
        root.after(10_000, update_status)


# ────────────────────────────────────────────────────────────────────────────
# Wi‑Fi and orientation handlers (unchanged except for logging tweaks)
# ────────────────────────────────────────────────────────────────────────────
def handle_wifi_data(data: str) -> None:
    """
    Expects:  "MySSID;PASS:supersecret"
    Creates a single key‑file profile with stored PSK (no user prompt).
    """
    log_debug("Handling WiFi data: " + data)
    try:
        ssid, pass_part = data.split(';', 1)
        password = pass_part.split(':', 1)[1]
    except ValueError:
        log_debug("WiFi payload malformed; expected SSID;PASS:pwd")
        return

    # wipe previous Wi‑Fi profiles
    try:
        profiles = subprocess.check_output(
            ["nmcli", "-t", "-f", "UUID,TYPE", "connection", "show"],
            text=True
        ).splitlines()
        for line in profiles:
            uuid, ctype = line.split(':', 1)
            if ctype == "802-11-wireless":
                subprocess.run(["nmcli", "connection", "delete", uuid],
                               check=False,
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError as exc:
        log_debug(f"Could not list profiles: {exc.stderr.strip()}")

    # add new profile
    try:
        subprocess.run(
            ["nmcli", "connection", "add",
             "type", "wifi",
             "ifname", "wlan0",
             "con-name", ssid,
             "ssid", ssid,
             "wifi-sec.key-mgmt", "wpa-psk",
             "wifi-sec.psk", password,
             "802-11-wireless-security.psk-flags", "0",
             "connection.autoconnect", "yes"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        subprocess.run(["nmcli", "connection", "reload"], check=True)
        subprocess.run(["nmcli", "connection", "up", ssid], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log_debug(f"Activated Wi‑Fi connection '{ssid}' non‑interactively.")
    except subprocess.CalledProcessError as exc:
        log_debug(f"nmcli error {exc.returncode}: {exc.stderr.strip() or exc.stdout.strip()}")


def handle_orientation_change(transform: str) -> None:
    """
    transform: "normal" | "90" | "180" | "270"
    Generates a kanshi config on the fly and restarts kanshi.
    """
    output = "HDMI-A-1"
    try:
        mode = subprocess.check_output(
            "wlr-randr | grep '(current)' | awk '{print $1\"@\"$3}'",
            shell=True, text=True
        ).strip()
    except subprocess.CalledProcessError as exc:
        log_debug(f"Failed to detect current mode: {exc}")
        return

    cfg_text = (f"profile {{\n"
                f"    output {output} enable mode {mode} position 0,0 "
                f"transform {transform}\n}}")

    cfg_path = Path.home() / ".config" / "kanshi" / "config"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(cfg_text)
    cfg_path.chmod(0o600)
    log_debug(f"Wrote kanshi config: mode={mode}, transform={transform}")

    subprocess.run(["killall", "kanshi"], check=False)
    subprocess.Popen(["kanshi", "-c", str(cfg_path)],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log_debug(f"Rotated {output} → {transform}° via kanshi")


# ────────────────────────────────────────────────────────────────────────────
# BLE plumbing (unchanged)
# ────────────────────────────────────────────────────────────────────────────
def ble_callback(value, options):
    try:
        if value is None:
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
    except Exception as exc:
        log_debug(f"Error in ble_callback: {exc}")


def start_gatt_server():
    while True:
        try:
            dongles = adapter.Adapter.available()
            if not dongles:
                log_debug("No Bluetooth adapters available for GATT server!")
                time.sleep(5)
                continue
            dongle_addr = list(dongles)[0].address
            log_debug(f"Using Bluetooth adapter for GATT server: {dongle_addr}")

            ble = peripheral.Peripheral(dongle_addr, local_name="PixelPaper")
            ble.add_service(srv_id=1, uuid=PROVISIONING_SERVICE_UUID, primary=True)
            ble.add_characteristic(
                srv_id=1, chr_id=1, uuid=PROVISIONING_CHAR_UUID,
                value=[], notifying=False,
                flags=['write', 'write-without-response'],
                write_callback=ble_callback
            )
            ble.add_characteristic(
                srv_id=1, chr_id=2, uuid=SERIAL_CHAR_UUID,
                value=list(get_serial_number().encode()),
                flags=['read'],
                read_callback=lambda options: list(get_serial_number().encode())
            )
            log_debug("Publishing GATT server for provisioning and serial...")
            ble.publish()
            log_debug("GATT server event loop ended (disconnect).")
        except Exception as exc:
            log_debug(f"Exception in start_gatt_server: {exc}")
        log_debug("Restarting GATT server in 5 s…")
        time.sleep(5)


def start_gatt_server_thread():
    threading.Thread(target=start_gatt_server, daemon=True).start()


# ────────────────────────────────────────────────────────────────────────────
# GUI bootstrap
# ────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    root = tk.Tk()
    root.title("Frame Status")
    root.attributes('-fullscreen', False)

    label = tk.Label(root, text="Checking Wi‑Fi…", font=("Helvetica", 48))
    label.pack(expand=True)

    debug_text = tk.Text(root, height=10, bg="#f0f0f0")
    debug_text.pack(fill=tk.X, side=tk.BOTTOM)
    debug_text.config(state=tk.DISABLED)

    disable_pairing()
    start_gatt_server_thread()
    update_status()               # kick off 10‑s loop
    root.mainloop()
