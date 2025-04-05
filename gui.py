#!/usr/bin/env python3
import tkinter as tk
import socket
import subprocess
import time
import threading
import re  # Import regex for parsing
from bluezero import adapter, peripheral

# Global GUI variables and flags.
launched = False
debug_messages = []
provisioning_char = None
serial_char = None # Global ref for serial characteristic

# --- Constants ---
DEVICE_NAME = "PixelPaper" # Consistent device name

# Service and Characteristic UUIDs
PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"

# NEW: Device Information Service and Serial Number Characteristic UUIDs
DEVICE_INFO_SERVICE_UUID  = "0000180a-0000-1000-8000-00805f9b34fb" # Standard Device Information Service UUID
SERIAL_NUMBER_CHAR_UUID   = "00002a25-0000-1000-8000-00805f9b34fb" # Standard Serial Number String Characteristic UUID

# --- Utility Functions ---

def log_debug(message):
    """Logs debug messages to the GUI text widget and prints them to console."""
    global debug_text
    # Ensure updates happen on the main thread if called from another thread
    def update_gui():
        debug_messages.append(str(message)) # Ensure it's a string
        # Limit log length to the last 10 messages.
        debug_text.config(state=tk.NORMAL)
        debug_text.delete(1.0, tk.END)
        debug_text.insert(tk.END, "\n".join(debug_messages[-10:]))
        debug_text.config(state=tk.DISABLED)
        debug_text.see(tk.END) # Scroll to the bottom
    # Schedule the GUI update on the main thread
    if root and root.winfo_exists():
         root.after(0, update_gui)
    print(message)


def get_cpu_serial():
    """Retrieves the CPU serial number from /proc/cpuinfo."""
    try:
        with open('/proc/cpuinfo', 'r') as f:
            for line in f:
                if line.startswith('Serial'):
                    # Use regex to find the hexadecimal serial number
                    match = re.search(r':\s*([0-9a-fA-F]+)', line)
                    if match:
                        serial = match.group(1)
                        log_debug(f"Found CPU Serial: {serial}")
                        return serial
        log_debug("Could not find Serial in /proc/cpuinfo")
        return "UnknownSerial" # Fallback
    except FileNotFoundError:
        log_debug("Error: /proc/cpuinfo not found.")
        return "UnknownSerial" # Fallback
    except Exception as e:
        log_debug(f"Error reading CPU serial: {e}")
        return "UnknownSerial" # Fallback

def check_wifi_connection():
    """Test for internet connectivity by connecting to Google DNS."""
    # (Your existing function - unchanged)
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
    # (Your existing function - largely unchanged)
    global launched
    connected = check_wifi_connection()
    if connected and not launched:
        label.config(text="WiFi Connected. Launching frame...")
        log_debug("WiFi connected, launching browser.")
        launched = True
        try:
            subprocess.Popen([
                "chromium",
                "--noerrdialogs",
                "--disable-infobars",
                "--kiosk",
                "https://pixelpaper.com/frame.html"
            ])
            # Gracefully exit the Tkinter loop after launching
            if root and root.winfo_exists():
                root.after(1000, root.destroy) # Give a second before destroying
        except FileNotFoundError:
            log_debug("Error: chromium command not found. Cannot launch browser.")
            label.config(text="Error launching browser!")
        except Exception as e:
            log_debug(f"Error launching chromium: {e}")
            label.config(text="Error launching browser!")

    elif not connected:
        label.config(text="WiFi Not Connected. Waiting...")
        if root and root.winfo_exists():
             # Check again sooner if not connected
             root.after(3000, update_status)
    else: # Connected but already launched
        pass # Do nothing, browser is running

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
        # TODO: Add actual WiFi provisioning logic here based on 'credentials'
        # Example: Parse "WIFI:ssid;PASS:password;"
        # Connect using nmcli or similar tool

        # After processing, maybe update the status label
        if root and root.winfo_exists():
            root.after(0, lambda: label.config(text="Credentials Received. Connecting..."))
            root.after(1000, update_status) # Re-check connection status

    except Exception as e:
        log_debug("Error in wifi_write_callback: " + str(e))

def start_gatt_server():
    """Continuously sets up and publishes a BLE GATT server for provisioning."""
    global provisioning_char, serial_char

    # Get the unique serial number ONCE
    pixelpaper_serial = "PX" + get_cpu_serial()
    log_debug(f"Using identifier: {pixelpaper_serial}")
    serial_bytes = pixelpaper_serial.encode('utf-8') # Encode to bytes

    while True:
        ble_periph = None # Ensure it's reset in case of loop due to error
        try:
            dongles = list(adapter.Adapter.available())
            if not dongles:
                log_debug("No Bluetooth adapters available!")
                time.sleep(5)
                continue

            dongle = dongles[0]
            log_debug(f"Using Bluetooth adapter: {dongle.address} ({dongle.name})")

            # Ensure adapter is powered on
            if not dongle.powered:
                log_debug("Powering on Bluetooth adapter...")
                dongle.powered = True
                time.sleep(1) # Give it a moment

            # Create a Peripheral object
            ble_periph = peripheral.Peripheral(dongle.address, local_name=DEVICE_NAME, appearance=1344) # 1344 = Generic Tag

            # --- Provisioning Service ---
            ble_periph.add_service(srv_id=1, uuid=PROVISIONING_SERVICE_UUID, primary=True)
            provisioning_char = ble_periph.add_characteristic(
                srv_id=1,
                chr_id=1,
                uuid=PROVISIONING_CHAR_UUID,
                value=[],
                notifying=False,
                flags=['write', 'write-without-response'], # Keep write for credentials
                write_callback=wifi_write_callback,
                read_callback=None, # No read needed for provisioning char
                notify_callback=None
            )
            log_debug(f"Added Provisioning Characteristic: {PROVISIONING_CHAR_UUID}")

            # --- Device Information Service ---
            ble_periph.add_service(srv_id=2, uuid=DEVICE_INFO_SERVICE_UUID, primary=True)
            serial_char = ble_periph.add_characteristic(
                srv_id=2,
                chr_id=1,
                uuid=SERIAL_NUMBER_CHAR_UUID,
                value=serial_bytes,   # Set the initial value to the serial number bytes
                notifying=False,
                flags=['read'],       # READ ONLY characteristic
                write_callback=None,  # No writing allowed
                read_callback=None,   # Bluezero handles read internally for static value
                notify_callback=None
            )
            log_debug(f"Added Serial Number Characteristic: {SERIAL_NUMBER_CHAR_UUID} with value: {pixelpaper_serial}")

            # --- Start Advertising ---
            log_debug(f"Starting BLE advertising as '{DEVICE_NAME}'...")
            ble_periph.publish() # This blocks until the event loop stops

            # If publish() returns, it means the peripheral loop ended (e.g., adapter reset)
            log_debug("BLE peripheral event loop stopped. Will restart.")

        except Exception as e:
            log_debug(f"!!! Exception in GATT server loop: {e}")
            # Clean up peripheral if it exists
            if ble_periph and hasattr(ble_periph, 'remove_service'):
                 try:
                     log_debug("Attempting to clean up BLE services...")
                     # You might need to remove services in reverse order or handle potential errors here
                     # For simplicity, we just log and rely on restarting
                 except Exception as cleanup_e:
                     log_debug(f"Error during BLE cleanup: {cleanup_e}")

        log_debug("Restarting GATT server in 5 seconds...")
        time.sleep(5)


def start_gatt_server_thread():
    """Starts the GATT server in a background daemon thread."""
    log_debug("Starting GATT server thread...")
    t = threading.Thread(target=start_gatt_server, name="GATTServerThread", daemon=True)
    t.start()

# --- Main GUI Setup ---
root = None # Define root globally for access in log_debug and update_status
debug_text = None

if __name__ == '__main__':
    root = tk.Tk()
    root.title("PixelPaper Status")
    root.attributes('-fullscreen', True)
    root.configure(bg='black') # Set background color

    # Main status label.
    label = tk.Label(root, text="Initializing...", font=("Helvetica", 36), fg='white', bg='black')
    label.pack(expand=True)

    # Text widget for visual debugging.
    debug_text = tk.Text(root, height=8, width=80, bg="#333", fg="#ccc", font=("Courier", 10), state=tk.DISABLED, wrap=tk.WORD)
    debug_text.pack(fill=tk.X, side=tk.BOTTOM, padx=10, pady=10)

    log_debug("GUI Initialized.")

    # Start the BLE GATT server in a background thread.
    start_gatt_server_thread()

    # Begin checking WiFi connection and updating the UI.
    root.after(1000, update_status) # Start check after 1 sec

    root.mainloop()
    log_debug("GUI main loop finished.")