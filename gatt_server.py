#!/usr/bin/env python3
"""
gatt_server.py
A simple BLE GATT server for PixelPaper provisioning using Bluezero.
"""

import sys
from bluezero import peripheral
import re
import subprocess

def get_adapter_address():
    """
    Automatically retrieve the Bluetooth adapter address using hciconfig.
    Returns the MAC address of hci0 if found, or None otherwise.
    """
    try:
        result = subprocess.run(["hciconfig"], capture_output=True, text=True)
        match = re.search(r"BD Address:\s+([0-9A-F:]+)", result.stdout, re.IGNORECASE)
        if match:
            adapter_addr = match.group(1)
            print("Detected adapter address:", adapter_addr)
            return adapter_addr
        else:
            print("No Bluetooth adapter found.")
            return None
    except Exception as e:
        print("Error fetching adapter address:", e)
        return None

# Define your custom service and characteristic UUIDs.
FRAME_SERVICE_UUID = '12345678-1234-5678-1234-56789abcdef0'
FRAME_CHAR_UUID = '12345678-1234-5678-1234-56789abcdef1'

# Auto-detect the adapter address.
ADAPTER_ADDRESS = get_adapter_address()
if ADAPTER_ADDRESS is None:
    print("Cannot start GATT server without a Bluetooth adapter.")
    sys.exit(1)

def read_callback():
    """Return the current provisioning status or a placeholder value."""
    print("GATT: Read request received.")
    return b"Provisioning data"

def write_callback(value, options):
    """Process the provisioning data sent from the mobile app."""
    print("GATT: Write request received. Data:", value)
    # TODO: Parse and store the received credentials.
    return

# Create the Peripheral (GATT server) object with the adapter address and local name.
my_peripheral = peripheral.Peripheral(ADAPTER_ADDRESS, local_name='PixelPaper')

# Add a service (srv_id=1) with the custom service UUID.
my_peripheral.add_service(srv_id=1, uuid=FRAME_SERVICE_UUID, primary=True)

# Add a characteristic (chr_id=1) with the custom characteristic UUID.
my_peripheral.add_characteristic(srv_id=1,
                                 chr_id=1,
                                 uuid=FRAME_CHAR_UUID,
                                 value=b'Initial Value',
                                 notifying=False,
                                 flags=['read', 'write'],
                                 read_callback=read_callback,
                                 write_callback=write_callback)

print("Starting GATT server...")
try:
    my_peripheral.publish()
except KeyboardInterrupt:
    print("GATT server stopped.")
    sys.exit(0)
