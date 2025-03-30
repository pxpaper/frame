#!/bin/bash
# scripts/bluetooth_provision.sh

echo "[DEBUG] Enabling Bluetooth provisioning mode..."

# Start Bluetooth non-interactively.
sudo -n /usr/bin/systemctl start bluetooth

# Use bluetoothctl to reset any existing agent, then set up pairing.
bluetoothctl <<EOF
power on
agent off
agent on
default-agent
discoverable on
pairable on
EOF

echo "[DEBUG] Bluetooth provisioning mode enabled. Device is discoverable and pairable."
