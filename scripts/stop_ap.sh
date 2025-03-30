#!/bin/bash
# scripts/stop_ap.sh

echo "[DEBUG] Stopping AP mode and switching to client mode..."

# Stop AP services
sudo -n systemctl stop hostapd && echo "[DEBUG] hostapd stopped."
sudo -n systemctl stop dnsmasq && echo "[DEBUG] dnsmasq stopped."

# Read WiFi credentials from the configuration file.
WIFI_CONFIG="/home/orangepi/frame/config/wifi-config.json"
if [ ! -f "$WIFI_CONFIG" ]; then
  echo "[ERROR] WiFi configuration file not found!"
  exit 1
fi

# Debug output for credentials (avoid printing sensitive info in production)
SSID=$(jq -r '.ssid' "$WIFI_CONFIG")
echo "[DEBUG] Retrieved SSID: $SSID"

# Use jq to extract the password as well (if you want to verify it's non-empty, for example)
PASSWORD=$(jq -r '.password' "$WIFI_CONFIG")
[ -z "$PASSWORD" ] && echo "[ERROR] Password is empty!" || echo "[DEBUG] Password retrieved."

# Create a new wpa_supplicant configuration file.
echo "[DEBUG] Creating new wpa_supplicant configuration..."
sudo tee /etc/wpa_supplicant/wpa_supplicant.conf > /dev/null <<EOF
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=US

network={
    ssid="$SSID"
    psk="$PASSWORD"
    key_mgmt=WPA-PSK
}
EOF
echo "[DEBUG] wpa_supplicant.conf updated."

# Reconfigure the WiFi interface (assuming wlan0).
echo "[DEBUG] Reconfiguring wlan0..."
sudo -n wpa_cli -i wlan0 reconfigure && echo "[DEBUG] wlan0 reconfigured."
echo "[DEBUG] Client mode configured. Attempting to connect to $SSID."
