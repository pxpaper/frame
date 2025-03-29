#!/bin/bash
cd /home/orangepi/frame || exit

echo "Pulling latest code from GitHub..."
git fetch origin
echo "Resetting local changes..."
git reset --hard origin/main
git clean -fd

# Ensure scripts have the correct executable permissions
chmod +x update.sh
chmod +x scripts/launch_kiosk.sh

echo "Installing dependencies..."
npm install

echo "Reloading PM2 process..."
pm2 reload frame-server

echo "Update complete at $(date)"
