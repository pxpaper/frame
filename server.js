// server.js
//
const express = require('express');
const http = require('http');
const QRCode = require('qrcode');
const bodyParser = require('body-parser');
const fs = require('fs');
const path = require('path');
const { exec } = require('child_process');

const app = express();
const server = http.createServer(app);

// Parse JSON and URL-encoded data
app.use(bodyParser.json());
app.use(express.urlencoded({ extended: true }));
app.use(express.static(path.join(__dirname, 'public')));

const wifiConfigPath = path.join(__dirname, 'config', 'wifi-config.json');

// Helper function: Check if WiFi credentials exist
const wifiCredentialsExist = () => fs.existsSync(wifiConfigPath);

// Route: If WiFi is not configured, redirect to setup page
app.get('/', (req, res) => {
  if (!wifiCredentialsExist()) {
    res.redirect('/setup');
  } else {
    // Optionally, show a "configuring" page while the device connects.
    res.send(`<html>
      <head><title>Configuring...</title></head>
      <body>
        <h1>WiFi Configured</h1>
        <p>The device is connecting to your network...</p>
      </body>
    </html>`);
  }
});

// Route: Setup page for WiFi configuration
app.get('/setup', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'setup.html'));
});

// Route: Generate and display QR code for setup URL
app.get('/setup/qrcode', (req, res) => {
  const setupURL = `http://${req.headers.host}/setup`;
  QRCode.toDataURL(setupURL, (err, url) => {
    if (err) {
      res.status(500).send('Error generating QR code');
    } else {
      res.send(`<html>
        <head><title>QR Code</title></head>
        <body>
          <h1>Scan to Setup WiFi</h1>
          <img src="${url}" alt="QR Code">
        </body>
      </html>`);
    }
  });
});

// Route: Handle WiFi credentials submission from the captive portal
app.post('/setup/wifi', (req, res) => {
  const { ssid, password } = req.body;
  if (!ssid || !password) {
    return res.status(400).send('Missing credentials');
  }
  // Save credentials to config/wifi-config.json
  const wifiData = { ssid, password };
  fs.writeFileSync(wifiConfigPath, JSON.stringify(wifiData, null, 2));
  
  // Send confirmation to the user and refresh after a delay
  res.send(`<html>
    <head>
      <meta http-equiv="refresh" content="5; URL='/'" />
      <title>Setup Complete</title>
    </head>
    <body>
      <h1>WiFi credentials saved.</h1>
      <p>The device will now switch to client mode and connect to your network.</p>
    </body>
  </html>`);
  
  // Delay a few seconds to allow the user to read the page, then switch modes.
  setTimeout(() => {
    // Execute the script to stop AP mode and configure client mode.
    exec('bash scripts/stop_ap.sh', (error, stdout, stderr) => {
      if (error) {
        console.error(`Error stopping AP mode: ${error}`);
        return;
      }
      console.log(`AP mode stopped: ${stdout}`);
      // After switching to client mode, launch kiosk mode.
      exec('bash scripts/launch_kiosk.sh', (error, stdout, stderr) => {
        if (error) {
          console.error(`Error launching kiosk mode: ${error}`);
          return;
        }
        console.log(`Kiosk mode launched: ${stdout}`);
      });
    });
  }, 5000);
});

server.listen(PORT, '0.0.0.0', () => console.log(`Server running on port ${PORT}`));
