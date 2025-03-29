// ecosystem.config.js
//
module.exports = {
    apps: [
      {
        name: "frame-server",
        script: "./server.js",
        instances: 1,
        exec_mode: "fork",
        watch: false
      }
    ]
  };
  