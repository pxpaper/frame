#!/usr/bin/env python3
import tkinter as tk
import socket
import subprocess
import time
import threading
from bluezero import adapter, peripheral

# Global GUI variables and flags.
launched = False
debug_messages = []
provisioning_char = None

# UUIDs for custom provisioning service and characteristics.
PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"
SERIAL_CHAR_UUID          = "12345678-1234-5678-1234-56789abcdef2"

def get_serial_number():
    try:
        with open('/proc/device-tree/serial-number', 'r') as f:
            serial = f.read().strip('\x00\n ')
        return "PX" + serial
    except Exception as e:
        return "PXunknown"

def log_debug(message):
    global debug_text
    debug_messages.append(message)
    # Limit log length to the last 10 messages.
    debug_text.config(state=tk.NORMAL)
    debug_text.delete(1.0, tk.END)
    debug_text.insert(tk.END, "\n".join(debug_messages[-10:]))
    debug_text.config(state=tk.DISABLED)
    print(message)

def disable_pairing():
    try:
        result = subprocess.run(
            ["bluetoothctl"],
            input="pairable no\nquit\n",
            text=True,
            capture_output=True,
            check=True
        )
        log_debug("Pairing disabled: " + result.stdout.strip())
    except Exception as e:
        log_debug("Failed to disable pairing: " + str(e))

def check_wifi_connection():
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=2)
        return True
    except OSError:
        return False

def update_status():
    global launched
    connected = check_wifi_connection()
    if connected and not launched:
        label.config(text="WiFi Connected. Launching frame...")
        log_debug("WiFi connected, launching browser.")
        launched = True
        subprocess.Popen([
            "chromium-browser",
            "--kiosk",
            "https://pixelpaper.com/frame.html"
        ])
        # Do not destroy the GUI so that BLE stays active.
    elif not connected:
        label.config(text="WiFi Not Connected. Waiting for connection...")
    root.after(5000, update_status)

def handle_wifi_data(data):
    """
    Expects `data` in the form "<SSID>;PASS:<password>".
    Uses wpa_cli to add (or update) the network, enable it,
    save the config, and reconfigure wpa_supplicant.
    """
    try:
        # Parse out SSID and password
        if ';PASS:' not in data:
            log_debug(f"Malformed WIFI data: {data}")
            return
        ssid, password = data.split(';PASS:', 1)
        ssid = ssid.strip()
        password = password.strip()
        log_debug(f"Configuring WiFi: SSID={ssid}")

        # 1) Add a new network
        out = subprocess.check_output(
            ['wpa_cli', '-i', 'wlan0', 'add_network'],
            text=True, stderr=subprocess.STDOUT
        ).strip()
        net_id = out
        log_debug(f"  → Created network id {net_id}")

        # 2) Set SSID and PSK for that network
        subprocess.check_call(
            ['wpa_cli', '-i', 'wlan0', 'set_network', net_id, 'ssid', f'"{ssid}"']
        )
        subprocess.check_call(
            ['wpa_cli', '-i', 'wlan0', 'set_network', net_id, 'psk', f'"{password}"']
        )
        log_debug("  → SSID and PSK set")

        # 3) Enable the network
        subprocess.check_call(
            ['wpa_cli', '-i', 'wlan0', 'enable_network', net_id]
        )
        log_debug(f"  → Enabled network {net_id}")

        # 4) Save the configuration so it persists across reboots
        subprocess.check_call(
            ['wpa_cli', '-i', 'wlan0', 'save_config']
        )
        log_debug("  → Saved wpa_supplicant configuration")

        # 5) Tell wpa_supplicant to reconfigure immediately
        subprocess.check_call(
            ['wpa_cli', '-i', 'wlan0', 'reconfigure']
        )
        log_debug("  → Reconfigured wpa_supplicant; should join new network shortly")

    except subprocess.CalledProcessError as e:
        log_debug(f"wpa_cli error ({e.returncode}): {e.output}")
    except Exception as e:
        log_debug(f"Error configuring WiFi: {e}")


def handle_orientation_change(data):
    # Process orientation change command.
    log_debug("Handling orientation change: " + data)
    # Add code for changing orientation here.
    # ...

def ble_callback(value, options):
    try:
        log_debug("Generic BLE write callback triggered!")
        # Decode the incoming bytes into a string.
        message = bytes(value).decode('utf-8')
        log_debug("Received BLE data: " + message)
        # Determine the command type and dispatch accordingly.
        if message.startswith("WIFI:"):
            wifi_data = message[len("WIFI:"):].strip()
            handle_wifi_data(wifi_data)
        elif message.startswith("ORIENT:"):
            orientation_data = message[len("ORIENT:"):].strip()
            handle_orientation_change(orientation_data)
        else:
            log_debug("Unknown BLE command received.")
    except Exception as e:
        log_debug("Error in generic_ble_callback: " + str(e))
    return

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
            ble_periph.add_service(srv_id=1, uuid=PROVISIONING_SERVICE_UUID, primary=True)
            provisioning_char = ble_periph.add_characteristic(
                srv_id=1,
                chr_id=1,
                uuid=PROVISIONING_CHAR_UUID,
                value=[],  # Start with an empty value.
                notifying=False,
                flags=['write', 'write-without-response'],
                write_callback=ble_callback,
                read_callback=None,
                notify_callback=None
            )
            # Add a read-only serial characteristic containing the serial number.
            ble_periph.add_characteristic(
                srv_id=1,
                chr_id=2,
                uuid=SERIAL_CHAR_UUID,
                value=list(get_serial_number().encode()),
                notifying=False,
                flags=['read'],
                read_callback=lambda options: list(get_serial_number().encode()),
                write_callback=None,
                notify_callback=None
            )
            log_debug("Publishing GATT server for provisioning and serial...")
            ble_periph.publish()
            log_debug("GATT server event loop ended (likely due to disconnection).")
        except Exception as e:
            log_debug("Exception in start_gatt_server: " + str(e))
        log_debug("Restarting GATT server in 5 seconds...")
        time.sleep(5)

def start_gatt_server_thread():
    """Starts the GATT server in a background daemon thread."""
    t = threading.Thread(target=start_gatt_server, daemon=True)
    t.start()

# --- Main GUI ---

if __name__ == '__main__':
    root = tk.Tk()
    root.title("Frame Status")
    root.attributes('-fullscreen', False)

    # Main status label.
    label = tk.Label(root, text="Checking WiFi...", font=("Helvetica", 48))
    label.pack(expand=True)

    # Text widget for visual debugging.
    debug_text = tk.Text(root, height=10, bg="#f0f0f0")
    debug_text.pack(fill=tk.X, side=tk.BOTTOM)
    debug_text.config(state=tk.DISABLED)

    # Disable pairing on startup.
    disable_pairing()

    # Always start the BLE GATT server.
    start_gatt_server_thread()

    # Begin checking WiFi connection and updating the UI.
    update_status()

    root.mainloop()
