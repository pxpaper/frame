#!/bin/bash
# scripts/setup_ap.sh
# Placeholder script to enable AP mode.
# Adjust commands according to your hardware and hostapd configuration.

echo "Setting up Access Point mode..."
sudo systemctl stop wpa_supplicant
sudo systemctl start hostapd
sudo systemctl start dnsmasq
echo "AP mode enabled."
