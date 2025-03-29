// server.js
const express = require('express');
const http = require('http');
const socketIO = require('socket.io');
const QRCode = require('qrcode');
const bodyParser = require('body-parser');
const fs = require('fs');
const path = require('path');

const app = express();
const server = http.createServer(app);
const io = socketIO(server);

// Middleware to parse JSON bodies
app.use(bodyParser.json());
app.use(express.urlencoded({ extended: true }));
app.use(express.static(path.join(__dirname, 'public')));

const wifiConfigPath = path.join(__dirname, 'config', 'wifi-config.json');

// Helper to check if WiFi credentials exist
const wifiCredentialsExist = () => fs.existsSync(wifiConfigPath);

// Route: Home - decide which page to serve based on WiFi setup
app.get('/', (req, res) => {
  if (!wifiCredentialsExist()) {
    // If WiFi credentials are missing, redirect to setup mode.
    res.redirect('/setup');
  } else {
    // Otherwise, serve the main application page.
    res.sendFile(path.join(__dirname, 'public', 'index.html'));
  }
});

// Route: Setup page to enter WiFi credentials and display QR code.
app.get('/setup', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'setup.html'));
});

// Route: Generate QR code for setup URL
app.get('/setup/qrcode', (req, res) => {
  const setupURL = `http://${req.headers.host}/setup`;
  QRCode.toDataURL(setupURL, (err, url) => {
    if (err) return res.status(500).send('Error generating QR code');
    res.send(`<html>
      <head>
        <title>WiFi Setup</title>
      </head>
      <body>
        <h1>Scan to Setup WiFi</h1>
        <img src="${url}" alt="QR Code">
      </body>
    </html>`);
  });
});

// Route: Handle WiFi credentials submission
app.post('/setup/wifi', (req, res) => {
  const { ssid, password } = req.body;
  if (!ssid || !password) {
    return res.status(400).send('Missing credentials');
  }
  // Save the credentials in a simple JSON file.
  fs.writeFileSync(wifiConfigPath, JSON.stringify({ ssid, password }, null, 2));
  res.send(`<html>
    <head>
      <meta http-equiv="refresh" content="3; URL='/'" />
      <title>Setup Complete</title>
    </head>
    <body>
      <h1>WiFi credentials saved.</h1>
      <p>The device will now restart into the main mode.</p>
    </body>
  </html>`);
});

// Route: Trigger a WiFi reset (for in-app or remote reset)
app.post('/reset', (req, res) => {
  if (wifiCredentialsExist()) {
    fs.unlinkSync(wifiConfigPath);
  }
  res.send({ success: true, message: 'Device reset to setup mode' });
});

// Socket.io: Listen for real-time connections and updates
io.on('connection', (socket) => {
  console.log('New client connected');
  // Example: send an update after 5 seconds (replace with real logic)
  setTimeout(() => {
    socket.emit('update', { message: 'New content available!' });
  }, 5000);

  socket.on('disconnect', () => {
    console.log('Client disconnected');
  });
});

// Start the server on port 3000
const PORT = process.env.PORT || 3000;
server.listen(PORT, () => console.log(`Server running on port ${PORT}`));
