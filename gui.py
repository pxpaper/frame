#!/usr/bin/env python3
import tkinter as tk
import socket
import subprocess

launched = False  # Flag to ensure we only launch once

def check_wifi_connection():
    """Attempt to connect to an external server (Google DNS) to test for internet access."""
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
        launched = True
        # Launch Chromium in kiosk mode pointing to the desired URL.
        subprocess.Popen([
            "chromium",
            "--noerrdialogs",
            "--disable-infobars",
            "--kiosk",
            "https://pxpaper.com/frame"
        ])
        # Close the Tkinter GUI once the browser has launched.
        root.destroy()
    elif not connected:
        label.config(text="WiFi Not Connected. Waiting for connection...")
        # Check again after 5 seconds if not connected.
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
