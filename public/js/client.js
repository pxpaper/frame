// public/js/client.js
const socket = io();

// Listen for updates from the server
socket.on('update', (data) => {
  console.log('Update received:', data);
  // Example: Update the content div with the new message
  const content = document.getElementById('content');
  content.innerHTML = `<h1>${data.message}</h1>`;
});
