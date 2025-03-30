// server.js
const express = require('express');
const http = require('http');
const QRCode = require('qrcode');
const bodyParser = require('body-parser');
const fs = require('fs');
const path = require('path');
const { exec } = require('child_process');

const app = express();
const server = http.createServer(app);

console.log("[DEBUG] Starting Node.js server...");

// Parse JSON and URL-encoded data
app.use(bodyParser.json());
app.use(express.urlencoded({ extended: true }));
app.use(express.static(path.join(__dirname, 'public')));

const wifiConfigPath = path.join(__dirname, 'config', 'wifi-config.json');

// Helper function: Check if WiFi credentials exist
const wifiCredentialsExist = () => fs.existsSync(wifiConfigPath);

/**
 * Function to execute a script and log output.
 * @param {string} cmd - Command to execute.
 * @param {function} callback - Callback after execution.
 */
const runScript = (cmd, callback) => {
  exec(cmd, (error, stdout, stderr) => {
    if (error) {
      console.error(`[ERROR] ${cmd} failed: ${error}`);
    }
    if (stdout) {
      console.log(`[DEBUG] ${cmd} output: ${stdout}`);
    }
    if (stderr) {
      console.error(`[DEBUG] ${cmd} error output: ${stderr}`);
    }
    if (callback) callback(error);
  });
};

// Route: If WiFi is not configured, redirect to setup page
app.get('/', (req, res) => {
  if (!wifiCredentialsExist()) {
    console.log("[DEBUG] No WiFi credentials found; redirecting to /setup");
    res.redirect('/setup');
  } else {
    console.log("[DEBUG] WiFi credentials found; serving configuring page");
    // You might show a "configuring" page until the kiosk mode launches.
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
  
  // After a delay, switch modes and launch kiosk mode.
  setTimeout(() => {
    runScript('bash scripts/stop_ap.sh', (error) => {
      if (!error) {
        runScript('bash scripts/launch_kiosk.sh');
      }
    });
  }, 5000);
});

// Start the server on port 3000 and perform initial network mode setup.
server.listen(3000, '0.0.0.0', () => {
  console.log("[DEBUG] Server running on port 3000");
  
  // If WiFi credentials exist, switch to client mode and launch kiosk mode.
  if (wifiCredentialsExist()) {
    console.log("[DEBUG] WiFi credentials found at boot. Switching to client mode...");
    runScript('bash scripts/stop_ap.sh', (error) => {
      if (!error) {
        console.log("[DEBUG] Launching kiosk mode...");
        runScript('bash scripts/launch_kiosk.sh');
      }
    });
  } else {
    // Otherwise, start in AP mode.
    console.log("[DEBUG] No WiFi credentials found at boot. Enabling AP mode...");
    runScript('bash scripts/setup_ap.sh');
  }
});
