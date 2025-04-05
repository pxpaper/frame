#!/usr/bin/env python3
import tkinter as tk
import socket
import subprocess
import time
import threading
from bluezero import adapter, peripheral, advertisement

# Global GUI variables and flags.
launched = False          # Flag to ensure we launch Chromium only once
debug_messages = []       # List for debug messages
provisioning_char = None  # Global reference to our provisioning characteristic

# UUIDs for our custom provisioning service and characteristic.
PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"

def get_serial_number():
    # For many Orange Pi boards, the serial number is in /proc/device-tree/serial-number
    try:
        with open('/proc/device-tree/serial-number', 'r') as f:
            serial = f.read().strip('\x00\n ')
            if serial:
                return serial
    except Exception:
        pass
    return "unknown"

def log_debug(message):
    """Logs debug messages to the GUI text widget and prints them to the console."""
    global debug_text
    debug_messages.append(message)
    # Limit log length to the last 10 messages.
    debug_text.config(state=tk.NORMAL)
    debug_text.delete(1.0, tk.END)
    debug_text.insert(tk.END, "\n".join(debug_messages[-10:]))
    debug_text.config(state=tk.DISABLED)
    print(message)

def check_wifi_connection():
    """Test for internet connectivity by connecting to Google DNS."""
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=2)
        return True
    except OSError:
        return False

def update_status():
    """
    Update GUI status: if WiFi is connected, launch Chromium (only once)
    while keeping the Tkinter window running (for Bluetooth functionality).
    """
    global launched
    connected = check_wifi_connection()
    if connected and not launched:
        label.config(text="WiFi Connected. Launching frame...")
        log_debug("WiFi connected, launching browser.")
        launched = True
        subprocess.Popen([
            "chromium",
            "--noerrdialogs",
            "--disable-infobars",
            "--kiosk",
            "https://pixelpaper.com/frame.html"
        ])
        # Do not destroy the window so that Bluetooth continues to run.
    elif not connected:
        label.config(text="WiFi Not Connected. Waiting for connection...")
    # Call update_status again in 5 seconds.
    root.after(5000, update_status)

# --- Bluezero Advertisement ---

def start_advertisement():
    """
    Creates and registers an advertisement that includes manufacturer data.
    The manufacturer data contains the serial number, prepended with "PX".
    """
    try:
        serial = get_serial_number()
        mfg_data = bytearray("PX" + serial, 'utf-8')
        # Create an advertisement: use ad_type "peripheral" and adapter index 0.
        ad = advertisement.Advertisement("peripheral", 0)
        ad.local_name = "PixelPaper"
        ad.manufacturer_data = {0xFFFF: mfg_data}  # Using 0xFFFF as example manufacturer ID.
        ad.service_UUIDs = [PROVISIONING_SERVICE_UUID]
        ad.register()
        log_debug("Advertisement registered with manufacturer data: PX" + serial)
    except Exception as e:
        log_debug("Advertisement error: " + str(e))

# --- Bluezero GATT Server Functions ---

def wifi_write_callback(value, options):
    """
    Write callback for our provisioning characteristic.
    Called when a mobile app writes WiFi credentials (or other commands) via BLE.
    'value' is a list of integers representing the bytes sent.
    """
    try:
        log_debug("wifi_write_callback triggered!")
        credentials = bytes(value).decode('utf-8')
        log_debug("Received data via BLE: " + credentials)
        # No notification is sent back in this version.
    except Exception as e:
        log_debug("Error in wifi_write_callback: " + str(e))
    return

def start_gatt_server():
    """
    Continuously sets up and publishes a BLE GATT server for provisioning.
    If the peripheral disconnects, the loop restarts the server.
    """
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
            
            # Create a Peripheral object with a fixed local name.
            ble_periph = peripheral.Peripheral(dongle_addr, local_name="PixelPaper")
            ble_periph.add_service(srv_id=1, uuid=PROVISIONING_SERVICE_UUID, primary=True)
            provisioning_char = ble_periph.add_characteristic(
                srv_id=1,
                chr_id=1,
                uuid=PROVISIONING_CHAR_UUID,
                value=[],  # Start with an empty value.
                notifying=False,
                flags=['write', 'write-without-response'],
                write_callback=wifi_write_callback,
                read_callback=None,
                notify_callback=None
            )
            log_debug("Publishing GATT server for provisioning...")
            ble_periph.publish()  # Blocks until the peripheral event loop stops.
            log_debug("GATT server event loop ended (likely due to disconnection).")
        except Exception as e:
            log_debug("Exception in start_gatt_server: " + str(e))
        log_debug("Restarting GATT server in 5 seconds...")
        time.sleep(5)

def start_gatt_server_thread():
    """Starts the GATT server in a background daemon thread."""
    t = threading.Thread(target=start_gatt_server, daemon=True)
    t.start()

# --- Main GUI Setup ---

if __name__ == '__main__':
    root = tk.Tk()
    root.title("Frame Status")
    root.attributes('-fullscreen', True)

    # Main status label.
    label = tk.Label(root, text="Checking WiFi...", font=("Helvetica", 48))
    label.pack(expand=True)

    # Text widget for visual debugging.
    debug_text = tk.Text(root, height=10, bg="#f0f0f0")
    debug_text.pack(fill=tk.X, side=tk.BOTTOM)
    debug_text.config(state=tk.DISABLED)

    # Start the advertisement with manufacturer data.
    start_advertisement()

    # Start the BLE GATT server for provisioning in a background thread.
    start_gatt_server_thread()

    # Begin checking WiFi connection and updating the UI.
    update_status()
    root.mainloop()
