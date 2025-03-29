module.exports = {
    apps: [
      {
        name: "frame",
        script: "./server.js",
        cwd: "/home/orangepi/frame",  // Ensure this is the absolute path to your 'frame' folder
        instances: 1,
        exec_mode: "fork"
      }
    ]
  };
  