#!/usr/bin/env python3
import tkinter as tk
import socket
import subprocess
import qrcode
from PIL import Image, ImageTk

launched = False  # Flag to ensure we only launch once
qr_label = None   # Global widget for QR code display
qr_photo = None   # Global reference to the PhotoImage

def start_ble_advertising():
    """
    Configure the Bluetooth adapter to advertise with the name "PixelPaperFrame".
    This function uses BlueZ tools to bring up the interface, enable advertising, 
    and set the advertisement data. The advertisement data is built to advertise
    the complete local name.
    """
    try:
        # Bring up the Bluetooth interface.
        subprocess.run(["sudo", "hciconfig", "hci0", "up"], check=True)
        # Enable LE advertising (using mode "3" which works for many setups).
        subprocess.run(["sudo", "hciconfig", "hci0", "leadv", "3"], check=True)
        # Construct advertisement data:
        # The first byte (0x10) is the length of this field (1 for type + 15 for "PixelPaperFrame").
        # The second byte (0x09) indicates "Complete Local Name".
        # The following bytes are the ASCII values for "PixelPaperFrame":
        #   P = 0x50, i = 0x69, x = 0x78, e = 0x65, l = 0x6C,
        #   P = 0x50, a = 0x61, p = 0x70, e = 0x65, r = 0x72,
        #   F = 0x46, r = 0x72, a = 0x61, m = 0x6D, e = 0x65.
        adv_cmd = [
            "sudo", "hcitool", "-i", "hci0", "cmd", "0x08", "0x0008",
            "0x10", "0x09", "0x50", "0x69", "0x78", "0x65", "0x6C",
            "0x50", "0x61", "0x70", "0x65", "0x72", "0x46", "0x72",
            "0x61", "0x6D", "0x65"
        ]
        subprocess.run(adv_cmd, check=True)
        print("BLE advertising started as 'PixelPaperFrame'")
    except Exception as e:
        print("Error starting BLE advertising:", e)

def check_wifi_connection():
    """Attempt to connect to an external server (Google DNS) to test for internet access."""
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=2)
        return True
    except OSError:
        return False

def generate_qr_code():
    """Generate a QR code image for Bluetooth provisioning.
    
    Replace the qr_data content with your actual provisioning information.
    """
    qr_data = "BT-CONNECT:frame-provisioning"  # Placeholder data for provisioning
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
        launched = True
        # Launch Chromium in kiosk mode pointing to the desired URL.
        subprocess.Popen([
            "chromium",
            "--noerrdialogs",
            "--disable-infobars",
            "--kiosk",
            "https://pixelpaper.com/frame.html"
        ])
        # Close the Tkinter GUI once the browser has launched.
        root.destroy()
    elif not connected:
        label.config(text="WiFi Not Connected. Waiting for connection...\nScan the QR code below for provisioning via Bluetooth.")
        # Generate the QR code image.
        img = generate_qr_code()
        # Convert the PIL image to a PhotoImage to display in Tkinter.
        qr_photo = ImageTk.PhotoImage(img)
        if qr_label is None:
            qr_label = tk.Label(root, image=qr_photo)
            qr_label.image = qr_photo  # Keep a reference!
            qr_label.pack(pady=20)
        else:
            qr_label.config(image=qr_photo)
            qr_label.image = qr_photo
        # Re-check the connection every 5 seconds.
        root.after(5000, update_status)

if __name__ == '__main__':
    # Start BLE advertising so that the device advertises as "PixelPaperFrame"
    start_ble_advertising()

    # Setup GUI for WiFi provisioning and status display.
    root = tk.Tk()
    root.title("Frame Status")
    # Set the window to full-screen mode.
    root.attributes('-fullscreen', True)
    
    label = tk.Label(root, text="Checking WiFi...", font=("Helvetica", 48))
    label.pack(expand=True)
    
    update_status()
    root.mainloop()
