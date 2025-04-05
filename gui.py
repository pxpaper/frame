#!/usr/bin/env python3
import tkinter as tk
import socket
import subprocess
import time
import threading
from bluezero import adapter, peripheral
import re # Import regex for parsing

# Global GUI variables and flags.
launched = False          # Flag to ensure we only launch once
debug_messages = []       # List for debug messages
provisioning_char = None  # Global reference to our provisioning characteristic
serial_char = None        # Global reference to the serial number characteristic

# UUIDs for our custom provisioning service and characteristic.
PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"
# Define a new UUID for the serial number characteristic
SERIAL_NUMBER_CHAR_UUID = "12345678-1234-5678-1234-56789abcdef2"

# --- Function to get CPU Serial ---
def get_cpu_serial():
    """Gets the CPU serial number from /proc/cpuinfo."""
    try:
        with open('/proc/cpuinfo', 'r') as f:
            for line in f:
                if line.startswith('Serial'):
                    # Extract the serial number (the part after ': ')
                    serial = line.split(':')[1].strip()
                    return "PX" + serial # Prepend "PX"
    except Exception as e:
        log_debug(f"Error reading serial number: {e}")
        return "PXUNKNOWN" # Return a default value on error
    return "PXNOTFOUND" # Return if Serial line not found

# --- Logging and WiFi Check (Unchanged) ---
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

# --- Modified update_status ---
def update_status():
    """
    Update GUI status: if WiFi is connected, launch the browser;
    otherwise, display a waiting message. Keeps running regardless.
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
        # *** REMOVED root.destroy() to keep the script and BLE running ***
        # Optionally hide the window if desired:
        # root.withdraw()
    elif not connected:
        label.config(text="WiFi Not Connected. Waiting for connection...")

    # Keep checking periodically even after launch,
    # in case status needs updating later or for debug.
    root.after(5000, update_status)


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
        # Implement credential processing logic here (e.g., save to wpa_supplicant)
        # Example: process_wifi_credentials(credentials)
    except Exception as e:
        log_debug("Error in wifi_write_callback: " + str(e))
    # No return value needed for write-without-response

# --- Modified start_gatt_server ---
def start_gatt_server():
    """Continuously sets up and publishes a BLE GATT server for provisioning and identification."""
    global provisioning_char, serial_char
    cpu_serial = get_cpu_serial() # Get serial once at the start
    log_debug(f"Device Serial Number: {cpu_serial}")

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

            # Add the provisioning characteristic (write-only)
            provisioning_char = ble_periph.add_characteristic(
                srv_id=1,
                chr_id=1, # Characteristic ID 1
                uuid=PROVISIONING_CHAR_UUID,
                value=[],
                notifying=False,
                flags=['write', 'write-without-response'],
                write_callback=wifi_write_callback,
                read_callback=None,
                notify_callback=None
            )
            log_debug("Added Provisioning Characteristic.")

            # Add the serial number characteristic (read-only)
            serial_char = ble_periph.add_characteristic(
                srv_id=1,
                chr_id=2, # Characteristic ID 2 (must be different from chr_id 1)
                uuid=SERIAL_NUMBER_CHAR_UUID,
                value=list(cpu_serial.encode('utf-8')), # Encode serial to bytes, then list of ints
                notifying=False,
                flags=['read'], # Only allow reading
                write_callback=None,
                read_callback=None, # Static value, no read callback needed
                notify_callback=None
            )
            log_debug(f"Added Serial Number Characteristic ({cpu_serial}).")


            log_debug("Publishing GATT server...")
            ble_periph.publish()
            log_debug("GATT server event loop ended (likely due to disconnection or error).")

        except Exception as e:
            log_debug("Exception in start_gatt_server: " + str(e))

        log_debug("Restarting GATT server in 5 seconds...")
        # Cleanup before restart (important!)
        if 'ble_periph' in locals() and ble_periph.published:
             try:
                 ble_periph.remove_service(1) # Attempt to clean up the service
             except Exception as cleanup_e:
                 log_debug(f"Error cleaning up service: {cleanup_e}")
        time.sleep(5)


def start_gatt_server_thread():
    """Starts the GATT server in a background daemon thread."""
    t = threading.Thread(target=start_gatt_server, daemon=True)
    t.start()

# --- Main GUI Setup (Unchanged) ---

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

    # Start the BLE GATT server for provisioning in a background thread.
    start_gatt_server_thread()

    # Begin checking WiFi connection and updating the UI.
    update_status()
    root.mainloop()