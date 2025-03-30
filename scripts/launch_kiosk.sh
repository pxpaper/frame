#!/bin/bash
# scripts/launch_kiosk.sh
# Check for internet connectivity and launch Chromium with the appropriate URL.

# Try pinging a reliable external IP (Google's DNS)
if ping -c 1 8.8.8.8 &> /dev/null; then
  URL="https://pixelpaper.com/frame.html"
else
  URL="http://localhost:3000/setup"
fi

echo "Launching kiosk mode with URL: $URL"
chromium --noerrdialogs --disable-infobars "$URL"
