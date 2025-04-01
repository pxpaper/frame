#!/usr/bin/env python3
import tkinter as tk
import socket
import subprocess
import time
import threading
from bluezero import adapter, peripheral, agent

# Global GUI variables and flags.
launched = False          # Flag to ensure we only launch once
debug_messages = []       # List for debug messages
provisioning_char = None  # Global reference to our provisioning characteristic

# UUIDs for our custom provisioning service and characteristic.
PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"

def log_debug(message):
    """Logs debug messages to the GUI text widget and prints them to console."""
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
    Update GUI status: if WiFi is connected, launch the browser;
    otherwise, display a waiting message.
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
        root.destroy()
    elif not connected:
        label.config(text="WiFi Not Connected. Waiting for connection...")
        root.after(5000, update_status)

# --- Bluezero GATT Server Functions ---

def wifi_write_callback(value, options):
    """
    Write callback for our provisioning characteristic.
    Called when a mobile app writes WiFi credentials via BLE.
    'value' is a list of integers representing the bytes sent.
    """
    try:
        log_debug("wifi_write_callback triggered!")
        credentials = bytes(value).decode('utf-8')
        log_debug("Received WiFi credentials via BLE: " + credentials)
        # For debugging, send back a confirmation notification.
        if provisioning_char is not None:
            provisioning_char.set_value(b"Credentials Received")
            log_debug("Sent confirmation notification.")
    except Exception as e:
        log_debug("Error in wifi_write_callback: " + str(e))
    return

def start_gatt_server():
    """Sets up and publishes a BLE GATT server for provisioning using Bluezero."""
    global provisioning_char
    try:
        dongles = adapter.Adapter.available()
        if not dongles:
            log_debug("No Bluetooth adapters available for GATT server!")
            return
        # Use the first available adapter.
        dongle_addr = list(dongles)[0].address
        log_debug("Using Bluetooth adapter for GATT server: " + dongle_addr)
        
        # Create a Peripheral object with a local name (e.g., "PixelPaperFrame").
        ble_periph = peripheral.Peripheral(dongle_addr, local_name="PixelPaperFrame")
        # Add a custom provisioning service.
        ble_periph.add_service(srv_id=1, uuid=PROVISIONING_SERVICE_UUID, primary=True)
        # Add a write+notify characteristic for WiFi provisioning.
        provisioning_char = ble_periph.add_characteristic(
            srv_id=1,
            chr_id=1,
            uuid=PROVISIONING_CHAR_UUID,
            value=[],  # Start with an empty value.
            notifying=False,
            flags=['write', 'notify'],
            write_callback=wifi_write_callback,
            read_callback=None,
            notify_callback=None
        )
        log_debug("Publishing GATT server for provisioning...")
        ble_periph.publish()  # This call starts the peripheral event loop.
        log_debug("GATT server published successfully.")
    except Exception as e:
        log_debug("Exception in start_gatt_server: " + str(e))

def start_gatt_server_thread():
    """Starts the GATT server in a background daemon thread."""
    t = threading.Thread(target=start_gatt_server, daemon=True)
    t.start()

# --- BlueZ Pairing Agent Functions ---

def start_pairing_agent():
    """
    Creates and runs a BlueZ agent with capability 'NoInputNoOutput'
    so that pairing requests are auto-accepted.
    """
    try:
        # Create an agent. The agent path here is arbitrary.
        ag = agent.Agent('/com/pixelpaper/agent', capability='NoInputNoOutput')
        log_debug("Pairing agent started with capability NoInputNoOutput.")
        ag.run()  # This call is blocking; run it in a separate thread.
    except Exception as e:
        log_debug("Exception in pairing agent: " + str(e))

def start_pairing_agent_thread():
    """Starts the pairing agent in a background daemon thread."""
    t = threading.Thread(target=start_pairing_agent, daemon=True)
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

    # Start the pairing agent so that pairing is auto-accepted.
    start_pairing_agent_thread()

    # Start the BLE GATT server for provisioning in a background thread.
    start_gatt_server_thread()

    # Begin checking WiFi connection and updating the UI.
    update_status()
    root.mainloop()
