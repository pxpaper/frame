#!/bin/bash
# scripts/stop_bluetooth.sh
# Disable Bluetooth provisioning mode.

echo "[DEBUG] Disabling Bluetooth provisioning mode..."

# Use bluetoothctl to turn off discoverability and pairability.
bluetoothctl <<EOF
discoverable off
pairable off
agent off
EOF

echo "[DEBUG] Bluetooth provisioning mode disabled."
