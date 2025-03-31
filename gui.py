#!/usr/bin/env python3
import tkinter as tk
import socket

def check_wifi_connection():
    """Attempt to connect to an external server to test for internet access.
       You can adjust the host/port if needed."""
    try:
        # Connect to Google's DNS server as a test (8.8.8.8 on port 53)
        socket.create_connection(("8.8.8.8", 53), timeout=2)
        return True
    except OSError:
        return False

def update_status():
    connected = check_wifi_connection()
    status_text = "WiFi Connected" if connected else "WiFi Not Connected"
    label.config(text=status_text)
    # Re-check connection every 5 seconds
    root.after(5000, update_status)

if __name__ == '__main__':
    root = tk.Tk()
    root.title("Frame Status")
    # Set the window to full-screen mode
    root.attributes('-fullscreen', True)
    
    label = tk.Label(root, text="Checking WiFi...", font=("Helvetica", 48))
    label.pack(expand=True)

    # Start periodic WiFi status updates
    update_status()

    root.mainloop()
