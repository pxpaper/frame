#!/usr/bin/env python3
import tkinter as tk
import socket
import subprocess
import time
import qrcode
from PIL import Image, ImageTk

launched = False  # Flag to ensure we only launch once
qr_label = None   # Global widget for QR code display
qr_photo = None   # Global reference to the PhotoImage
debug_messages = []  # List for debug messages

def log_debug(message):
    """Append a message to the debug log and update the debug text widget."""
    global debug_text
    debug_messages.append(message)
    # Limit log length to the last 10 messages.
    debug_text.config(state=tk.NORMAL)
    debug_text.delete(1.0, tk.END)
    debug_text.insert(tk.END, "\n".join(debug_messages[-10:]))
    debug_text.config(state=tk.DISABLED)
    print(message)  # Also print to console for additional debugging

def start_ble_advertising():
    """
    Configure the Bluetooth adapter using btmgmt to advertise with the name "PixelPaperFrame".
    Uses btmgmt commands to enable LE mode and advertising.
    """
    try:
        log_debug("Starting BLE advertising using btmgmt...")
        
        # Enable LE mode.
        result = subprocess.run(["sudo", "btmgmt", "le", "on"], capture_output=True, text=True)
        if result.returncode == 0:
            log_debug("btmgmt le on: SUCCESS")
        else:
            log_debug("btmgmt le on error: " + result.stderr.strip())

        # Enable advertising.
        result = subprocess.run(["sudo", "btmgmt", "advertising", "on"], capture_output=True, text=True)
        if result.returncode == 0:
            log_debug("btmgmt advertising on: SUCCESS")
        else:
            log_debug("btmgmt advertising on error: " + result.stderr.strip())
        
        # Wait a moment to allow the advertisement to start.
        log_debug("Waiting 3 seconds for BLE advertisement to stabilize...")
        time.sleep(3)
        
        # Optionally, check the status with btmgmt info.
        result = subprocess.run(["sudo", "btmgmt", "info"], capture_output=True, text=True)
        log_debug("btmgmt info:\n" + result.stdout.strip())
        
    except Exception as e:
        log_debug("Exception in start_ble_advertising: " + str(e))

def check_wifi_connection():
    """Attempt to connect to Google DNS to test for internet access."""
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=2)
        return True
    except OSError:
        return False

def generate_qr_code():
    """Generate a QR code image for Bluetooth provisioning."""
    qr_data = "BT-CONNECT:frame-provisioning"  # Placeholder provisioning data
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(qr_data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    return img

def update_status():
    global launched, qr_label, qr_photo
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
        label.config(text="WiFi Not Connected. Waiting for connection...\nScan the QR code below for provisioning via Bluetooth.")
        log_debug("WiFi not connected; displaying QR code.")
        # Generate the QR code image.
        img = generate_qr_code()
        # Convert the PIL image to a PhotoImage for Tkinter.
        qr_photo = ImageTk.PhotoImage(img)
        if qr_label is None:
            qr_label = tk.Label(root, image=qr_photo)
            qr_label.image = qr_photo  # Keep a reference!
            qr_label.pack(pady=20)
        else:
            qr_label.config(image=qr_photo)
            qr_label.image = qr_photo
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

    # Start BLE advertising using btmgmt.
    start_ble_advertising()

    update_status()
    root.mainloop()
