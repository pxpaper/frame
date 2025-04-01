#!/usr/bin/env python3
import tkinter as tk
import socket
import subprocess
import time
from bluezero import advertisement  # Bluezero API for BLE advertising

launched = False         # Flag to ensure we only launch once
debug_messages = []      # List for debug messages
ble_adv = None           # Global variable for the advertisement object

def log_debug(message):
    global debug_text
    debug_messages.append(message)
    # Limit log length to the last 10 messages.
    debug_text.config(state=tk.NORMAL)
    debug_text.delete(1.0, tk.END)
    debug_text.insert(tk.END, "\n".join(debug_messages[-10:]))
    debug_text.config(state=tk.DISABLED)
    print(message)  # Also print to console for additional debugging

def start_gatt_server():
    try:
        log_debug("Starting GATT server using venv interpreter...")
        # Launch the GATT server in the background.
        subprocess.Popen([
            "sudo",
            "/home/orangepi/frame/venv/bin/python3",
            "/home/orangepi/frame/gatt_server.py"
        ])
        log_debug("GATT server launched.")
    except Exception as e:
        log_debug("Failed to start GATT server: " + str(e))

def start_ble_advertising():
    global ble_adv
    try:
        log_debug("Starting BLE advertising using BlueZ API (Bluezero)...")
        # Create an advertisement for adapter hci0 as a peripheral.
        ble_adv = advertisement.Advertisement(0, 'peripheral')
        # Set the local name by assigning to the local_name attribute.
        ble_adv.local_name = "PixelPaper"
        # Optionally include TX power in the advertisement.
        ble_adv.include_tx_power = True
        # Register the advertisement with BlueZ.
        ble_adv.register()
        log_debug("BLE advertising registered via BlueZ API.")
    except Exception as e:
        log_debug("Exception in start_ble_advertising: " + str(e))

def check_wifi_connection():
    """Attempt to connect to Google DNS to test for internet access."""
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
        # Launch Chromium in kiosk mode pointing to the desired URL.
        subprocess.Popen([
            "chromium",
            "--noerrdialogs",
            "--disable-infobars",
            "--kiosk",
            "https://pixelpaper.com/frame.html"
        ])
        # Close the Tkinter GUI.
        root.destroy()
    elif not connected:
        label.config(text="WiFi Not Connected. Waiting for connection...")
        #log_debug("WiFi not connected; still waiting.")
        # Re-check connection every 5 seconds.
        root.after(5000, update_status)

if __name__ == '__main__':
    # Set up the main window.
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

    # Start the GATT server using your virtual environment.
    start_gatt_server()

    # Start BLE advertising using Bluezero.
    start_ble_advertising()

    # Start checking WiFi and update the GUI accordingly.
    update_status()
    root.mainloop()
