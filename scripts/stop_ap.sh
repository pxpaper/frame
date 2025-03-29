#!/bin/bash
# scripts/stop_ap.sh
# Stop AP mode and reconfigure WiFi for client mode.

echo "Stopping Access Point mode and switching to client mode..."

# Stop AP services
sudo systemctl stop hostapd
sudo systemctl stop dnsmasq

# Read WiFi credentials from the configuration file.
WIFI_CONFIG="/home/orangepi/frame/config/wifi-config.json"
if [ ! -f "$WIFI_CONFIG" ]; then
  echo "WiFi configuration file not found!"
  exit 1
fi

# Use jq to extract the SSID and password from the JSON file.
SSID=$(jq -r '.ssid' "$WIFI_CONFIG")
PASSWORD=$(jq -r '.password' "$WIFI_CONFIG")

# Create a new wpa_supplicant configuration file.
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

# Reconfigure the WiFi interface (assuming wlan0).
sudo wpa_cli -i wlan0 reconfigure
echo "Client mode configured. Attempting to connect to $SSID"
