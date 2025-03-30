#!/bin/bash
# scripts/setup_ap.sh

echo "[DEBUG] Starting AP mode setup..."
sudo systemctl stop wpa_supplicant && echo "[DEBUG] wpa_supplicant stopped."
sudo systemctl start hostapd && echo "[DEBUG] hostapd started."
sudo systemctl start dnsmasq && echo "[DEBUG] dnsmasq started."

echo "[DEBUG] AP mode enabled."

echo "[DEBUG] Current WiFi interface configuration:"
ip addr show wlan0

