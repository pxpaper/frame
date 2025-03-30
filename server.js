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

// Helper function: Check if WiFi credentials exist and are valid.
const wifiCredentialsExist = () => {
  if (!fs.existsSync(wifiConfigPath)) {
    return false;
  }
  try {
    const data = JSON.parse(fs.readFileSync(wifiConfigPath, 'utf8'));
    return data.ssid && data.password && data.ssid.trim() !== '' && data.password.trim() !== '';
  } catch (e) {
    console.error("[ERROR] wifi-config.json invalid:", e);
    return false;
  }
};

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
    console.log("[DEBUG] No valid WiFi credentials found; redirecting to /setup");
    res.redirect('/setup');
  } else {
    console.log("[DEBUG] Valid WiFi credentials found; serving configuring page");
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
  // Modify your setup page to instruct the user to use Bluetooth provisioning.
  res.sendFile(path.join(__dirname, 'public', 'setup.html'));
});

// Route: Generate and display QR code for setup instructions
app.get('/setup/qrcode', (req, res) => {
  // The QR code could encode a URL with instructions or a link to download the mobile app.
  const setupURL = `http://${req.headers.host}/setup`;
  QRCode.toDataURL(setupURL, (err, url) => {
    if (err) {
      res.status(500).send('Error generating QR code');
    } else {
      res.send(`<html>
        <head><title>QR Code</title></head>
        <body>
          <h1>Scan to Setup WiFi via Bluetooth</h1>
          <img src="${url}" alt="QR Code">
          <p>Please use our mobile app to connect via Bluetooth and share your WiFi credentials.</p>
        </body>
      </html>`);
    }
  });
});

// Route: Handle WiFi credentials submission from the provisioning app
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
      <p>The device will now use your network settings.</p>
    </body>
  </html>`);
  
  // After a delay, stop Bluetooth provisioning and launch kiosk mode.
  setTimeout(() => {
    runScript('bash scripts/stop_bluetooth.sh', (error) => {
      if (!error) {
        runScript('bash scripts/launch_kiosk.sh');
      }
    });
  }, 5000);
});

// Start the server on port 3000 and perform initial network mode setup.
server.listen(3000, '0.0.0.0', () => {
  console.log("[DEBUG] Server running on port 3000");
  
  if (wifiCredentialsExist()) {
    console.log("[DEBUG] Valid WiFi credentials found at boot. Switching to client mode...");
    // If credentials exist, ensure client mode is active (you might still call stop_bluetooth.sh if needed)
    runScript('bash scripts/stop_bluetooth.sh', (error) => {
      if (!error) {
        console.log("[DEBUG] Launching kiosk mode...");
        runScript('bash scripts/launch_kiosk.sh');
      }
    });
  } else {
    console.log("[DEBUG] No valid WiFi credentials found at boot. Enabling Bluetooth provisioning mode...");
    // Instead of starting AP mode, we now enable Bluetooth provisioning.
    runScript('bash scripts/bluetooth_provision.sh');
  }
});
