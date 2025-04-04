#!/usr/bin/env python3
import tkinter as tk
import socket
import subprocess
import time
import threading
from bluezero import adapter, peripheral

def get_serial_number():
    try:
        with open('/proc/cpuinfo', 'r') as f:
            for line in f:
                if line.startswith("Serial"):
                    return line.split(":")[1].strip()
    except Exception as e:
        return "unknown"

# Global GUI variables and flags.
launched = False          
debug_messages = []       
provisioning_char = None  

# UUIDs for our custom provisioning service and characteristic.
PROVISIONING_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
PROVISIONING_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1"

def log_debug(message):
    global debug_text
    debug_messages.append(message)
    debug_text.config(state=tk.NORMAL)
    debug_text.delete(1.0, tk.END)
    debug_text.insert(tk.END, "\n".join(debug_messages[-10:]))
    debug_text.config(state=tk.DISABLED)
    print(message)

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
            "chromium",
            "--noerrdialogs",
            "--disable-infobars",
            "--kiosk",
            "https://pixelpaper.com/frame.html"
        ])
        root.destroy()
    else:
        label.config(text="WiFi Not Connected. Waiting for connection...")
        root.after(5000, update_status)

def wifi_write_callback(value, options):
    try:
        log_debug("wifi_write_callback triggered!")
        credentials = bytes(value).decode('utf-8')
        log_debug("Received data via BLE: " + credentials)
    except Exception as e:
        log_debug("Error in wifi_write_callback: " + str(e))
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
            serial = get_serial_number()
            log_debug("Using Bluetooth adapter for GATT server: " + dongle_addr)
            
            # Publish the peripheral with a local name including the serial
            # and with service_data containing the serial.
            ble_periph = peripheral.Peripheral(
                dongle_addr,
                local_name=f"PixelPaper-{serial}",
                service_data={PROVISIONING_SERVICE_UUID: serial}
            )
            ble_periph.add_service(srv_id=1, uuid=PROVISIONING_SERVICE_UUID, primary=True)
            provisioning_char = ble_periph.add_characteristic(
                srv_id=1,
                chr_id=1,
                uuid=PROVISIONING_CHAR_UUID,
                value=[],
                notifying=False,
                flags=['write', 'write-without-response'],
                write_callback=wifi_write_callback,
                read_callback=None,
                notify_callback=None
            )
            log_debug("Publishing GATT server for provisioning...")
            ble_periph.publish()  
            log_debug("GATT server event loop ended (likely due to disconnection).")
        except Exception as e:
            log_debug("Exception in start_gatt_server: " + str(e))
        log_debug("Restarting GATT server in 5 seconds...")
        time.sleep(5)

def start_gatt_server_thread():
    t = threading.Thread(target=start_gatt_server, daemon=True)
    t.start()

if __name__ == '__main__':
    root = tk.Tk()
    root.title("Frame Status")
    root.attributes('-fullscreen', True)
    label = tk.Label(root, text="Checking WiFi...", font=("Helvetica", 48))
    label.pack(expand=True)
    debug_text = tk.Text(root, height=10, bg="#f0f0f0")
    debug_text.pack(fill=tk.X, side=tk.BOTTOM)
    debug_text.config(state=tk.DISABLED)
    start_gatt_server_thread()
    update_status()
    root.mainloop()
