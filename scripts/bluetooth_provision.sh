#!/bin/bash
# scripts/bluetooth_provision.sh
# Enable Bluetooth provisioning mode.

echo "[DEBUG] Enabling Bluetooth provisioning mode..."

# Ensure the Bluetooth service is running.
sudo systemctl start bluetooth

# Use bluetoothctl to set up the device for pairing.
bluetoothctl <<EOF
power on
agent on
default-agent
discoverable on
pairable on
EOF

echo "[DEBUG] Bluetooth provisioning mode enabled. Device is discoverable and pairable."
