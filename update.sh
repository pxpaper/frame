#!/bin/bash
# update.sh - Local update script for pulling code updates from GitHub

cd /home/orangepi/frame || exit
echo "Fetching latest code from GitHub..."
git fetch origin
echo "Resetting local changes..."
git reset --hard origin/main
git clean -fd
echo "Installing dependencies..."
npm install
echo "Reloading PM2 process..."
pm2 stop frame-server
pm2 start server.js --name frame-server
echo "Update complete at $(date)"