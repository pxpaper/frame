// server.js
const express = require('express');
const http = require('http');
const QRCode = require('qrcode');
const bodyParser = require('body-parser');
const fs = require('fs');
const path = require('path');
const { exec } = require('child_process');
const bleno = require('bleno');

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

// --- BLE GATT Server Setup using bleno --- //
const BlenoPrimaryService = bleno.PrimaryService;
const BlenoCharacteristic = bleno.Characteristic;

// Define fixed UUIDs for your provisioning service and characteristic.
// Note: bleno requires UUIDs without hyphens.
const PROVISIONING_SERVICE_UUID = "19b10000e8f2537e4f6cd104768a1214";
const CREDENTIALS_CHARACTERISTIC_UUID = "19b10001e8f2537e4f6cd104768a1217";

// Create a characteristic that will handle writing WiFi credentials.
class CredentialsCharacteristic extends BlenoCharacteristic {
  constructor() {
    super({
      uuid: CREDENTIALS_CHARACTERISTIC_UUID,
      properties: ['write'],
      value: null,
    });
  }
  
  onWriteRequest(data, offset, withoutResponse, callback) {
    try {
      // Convert the incoming data to a UTF-8 string.
      const payload = data.toString('utf8');
      console.log("[DEBUG] Received BLE credentials:", payload);
      // Parse the JSON payload.
      const credentials = JSON.parse(payload);
      // Save credentials to the config file.
      fs.writeFileSync(wifiConfigPath, JSON.stringify(credentials, null, 2));
      console.log("[DEBUG] WiFi credentials saved via BLE.");
      
      // Stop BLE advertising now that provisioning is complete.
      bleno.stopAdvertising();
      
      // Trigger client mode by running launch_kiosk.sh.
      runScript('bash scripts/launch_kiosk.sh');
      
      callback(this.RESULT_SUCCESS);
    } catch (error) {
      console.error("[ERROR] Failed to process BLE credentials:", error);
      callback(this.RESULT_UNLIKELY_ERROR);
    }
  }
}

// Create the provisioning service.
const provisioningService = new BlenoPrimaryService({
  uuid: PROVISIONING_SERVICE_UUID,
  characteristics: [new CredentialsCharacteristic()],
});
// --- End BLE GATT Server Setup --- //

// Express Routes

// Route: If WiFi is not configured, redirect to setup page.
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

// Route: Setup page for WiFi configuration.
app.get('/setup', (req, res) => {
  // Instruct the user to use Bluetooth provisioning.
  res.sendFile(path.join(__dirname, 'public', 'setup.html'));
});

// Route: Generate and display QR code for setup instructions.
app.get('/setup/qrcode', (req, res) => {
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

// Route: (Alternate HTTP-based provisioning)
app.post('/setup/wifi', (req, res) => {
  const { ssid, password } = req.body;
  if (!ssid || !password) {
    return res.status(400).send('Missing credentials');
  }
  const wifiData = { ssid, password };
  fs.writeFileSync(wifiConfigPath, JSON.stringify(wifiData, null, 2));
  
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
  
  // After a delay, stop BLE advertising and launch kiosk mode.
  setTimeout(() => {
    bleno.stopAdvertising();
    runScript('bash scripts/launch_kiosk.sh');
  }, 5000);
});

// Start the HTTP server on port 3000.
server.listen(3000, '0.0.0.0', () => {
  console.log("[DEBUG] Server running on port 3000");
  
  if (wifiCredentialsExist()) {
    console.log("[DEBUG] Valid WiFi credentials found at boot. Switching to client mode...");
    // If credentials exist, ensure BLE advertising is stopped and launch kiosk mode.
    bleno.stopAdvertising();
    runScript('bash scripts/launch_kiosk.sh');
  } else {
    console.log("[DEBUG] No valid WiFi credentials found at boot. Enabling BLE provisioning mode...");
    
    // Start BLE provisioning if the device is not provisioned.
    bleno.on('stateChange', (state) => {
      console.log("[DEBUG] BLE state:", state);
      if (state === 'poweredOn') {
        bleno.startAdvertising('Provisioner', [PROVISIONING_SERVICE_UUID], (err) => {
          if (err) {
            console.error("[ERROR] Failed to start advertising BLE:", err);
          } else {
            console.log("[DEBUG] BLE advertising started");
          }
        });
      } else {
        bleno.stopAdvertising();
      }
    });
    
    bleno.on('advertisingStart', (error) => {
      if (!error) {
        console.log("[DEBUG] Setting BLE provisioning service...");
        bleno.setServices([provisioningService]);
      } else {
        console.error("[ERROR] Advertising start error:", error);
      }
    });
  }
});
