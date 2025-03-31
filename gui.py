#!/usr/bin/env python3
import tkinter as tk
import socket
import subprocess
import qrcode
from PIL import Image, ImageTk

launched = False  # Flag to ensure we only launch once
qr_label = None   # Global widget for QR code display
qr_photo = None   # Global reference to the PhotoImage

# Create a list to hold debug messages.
debug_messages = []

def log_debug(message):
    """Append message to debug log and update the debug text widget."""
    global debug_text
    debug_messages.append(message)
    # Limit log length to the last 10 messages.
    debug_text.config(state=tk.NORMAL)
    debug_text.delete(1.0, tk.END)
    debug_text.insert(tk.END, "\n".join(debug_messages[-10:]))
    debug_text.config(state=tk.DISABLED)

def start_ble_advertising():
    """
    Configure the Bluetooth adapter to advertise with the name "PixelPaperFrame".
    This function uses BlueZ tools (hciconfig and hcitool) to bring up the interface, 
    enable advertising, and set the advertisement data.
    """
    try:
        log_debug("Starting BLE advertising...")
        # Bring up the Bluetooth interface.
        result = subprocess.run(["sudo", "hciconfig", "hci0", "up"],
                                capture_output=True, text=True)
        if result.returncode == 0:
            log_debug("hciconfig hci0 up: SUCCESS")
        else:
            log_debug(f"hciconfig hci0 up error: {result.stderr.strip()}")

        # Enable LE advertising (using mode "3").
        result = subprocess.run(["sudo", "hciconfig", "hci0", "leadv"],
                                capture_output=True, text=True)
        if result.returncode == 0:
            log_debug("hciconfig hci0 leadv 3: SUCCESS")
        else:
            log_debug(f"hciconfig hci0 leadv 3 error: {result.stderr.strip()}")

        # Construct advertisement data:
        # 0x10: Length (1 for type + 15 for "PixelPaperFrame")
        # 0x09: Type for Complete Local Name
        # Following bytes: ASCII for "PixelPaperFrame"
        adv_cmd = [
            "sudo", "hcitool", "-i", "hci0", "cmd", "0x08", "0x0008",
            "0x10", "0x09", "0x50", "0x69", "0x78", "0x65", "0x6C",
            "0x50", "0x61", "0x70", "0x65", "0x72", "0x46", "0x72",
            "0x61", "0x6D", "0x65"
        ]
        result = subprocess.run(adv_cmd, capture_output=True, text=True)
        if result.returncode == 0:
            log_debug("BLE advertising command: SUCCESS")
        else:
            log_debug(f"BLE advertising command error: {result.stderr.strip()}")
    except Exception as e:
        log_debug("Exception in start_ble_advertising: " + str(e))

def check_wifi_connection():
    """Attempt to connect to an external server (Google DNS) to test for internet access."""
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=2)
        return True
    except OSError:
        return False

def generate_qr_code():
    """Generate a QR code image for Bluetooth provisioning."""
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
        # Close the Tkinter GUI once the browser has launched.
        root.destroy()
    elif not connected:
        label.config(text="WiFi Not Connected. Waiting for connection...\nScan the QR code below for provisioning via Bluetooth.")
        log_debug("WiFi not connected; displaying QR code.")
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
    # Set up the root window.
    root = tk.Tk()
    root.title("Frame Status")
    root.attributes('-fullscreen', True)

    # Label to display main status.
    label = tk.Label(root, text="Checking WiFi...", font=("Helvetica", 48))
    label.pack(expand=True)

    # Create a Text widget for debug output.
    debug_text = tk.Text(root, height=10, bg="#f0f0f0")
    debug_text.pack(fill=tk.X, side=tk.BOTTOM)
    debug_text.config(state=tk.DISABLED)

    # Start BLE advertising so that the device advertises as "PixelPaperFrame"
    start_ble_advertising()

    update_status()
    root.mainloop()
