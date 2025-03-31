#!/usr/bin/env python3
import tkinter as tk
import socket
import subprocess
import qrcode
from PIL import Image, ImageTk

launched = False  # Flag to ensure we only launch once
qr_label = None   # Global widget for QR code display
qr_photo = None   # Global reference to the PhotoImage

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
    root = tk.Tk()
    root.title("Frame Status")
    # Set the window to full-screen mode.
    root.attributes('-fullscreen', True)
    
    label = tk.Label(root, text="Checking WiFi...", font=("Helvetica", 48))
    label.pack(expand=True)
    
    update_status()
    root.mainloop()
