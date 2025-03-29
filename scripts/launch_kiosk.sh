#!/bin/bash
# scripts/launch_kiosk.sh
# Launch Chromium in kiosk mode to display the digital picture frame webpage.

echo "Launching kiosk mode..."
chromium --noerrdialogs --disable-infobars https://pixelpaper.com/frame.html

#