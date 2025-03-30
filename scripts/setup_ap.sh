#!/bin/bash
# scripts/setup_ap.sh

echo "[DEBUG] Starting AP mode setup..."
sudo -n systemctl stop wpa_supplicant && echo "[DEBUG] wpa_supplicant stopped."
sudo -n systemctl start hostapd && echo "[DEBUG] hostapd started."
sudo -n systemctl start dnsmasq && echo "[DEBUG] dnsmasq started."

echo "[DEBUG] AP mode enabled."

echo "[DEBUG] Current WiFi interface configuration:"
ip addr show wlan0

