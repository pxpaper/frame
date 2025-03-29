#!/bin/bash
# update.sh - Local update script for pulling code updates from GitHub

cd /home/orangepi/frame || exit
echo "Pulling latest code..."
git pull origin main
echo "Installing dependencies..."
npm install
echo "Reloading PM2 process..."
pm2 stop frame-server
pm2 start server.js --name frame-server
echo "Update complete at $(date)"