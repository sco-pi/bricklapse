# BrickLapse Service Management

## Files

This directory contains systemd service files and startup scripts for running the Bricklapse application (web server and camera monitor) as Linux services. This allows the application to start automatically on boot, run in the background, and be easily managed.

## Installation

- `bricklapse-server.service` — systemd unit for the FastAPI web server
- `bricklapse-monitor.service` — systemd unit for the camera monitor script
- `start_server.sh` — startup script for the web server (runs in a screen session)
- `start_monitor.sh` — startup script for the camera monitor (runs in a screen session)


1. **Copy service files to systemd directory:**
```sh
sudo cp bricklapse-server.service /etc/systemd/system/
sudo cp bricklapse-monitor.service /etc/systemd/system/
```

2. **Make sure the startup scripts are executable:**
```sh
chmod +x /home/smurch/BrickLapsePython/service/start_server.sh
chmod +x /home/smurch/BrickLapsePython/service/start_monitor.sh
```

3. **Reload systemd to recognize new services:**
```sh
sudo systemctl daemon-reload
```

4. **Enable services to start on boot:**
```sh
sudo systemctl enable bricklapse-server
sudo systemctl enable bricklapse-monitor
```

5. **Start the services:**
```sh
sudo systemctl start bricklapse-server
sudo systemctl start bricklapse-monitor
```

## Service Management
- **Check status:**

```sh
sudo systemctl status bricklapse-server
sudo systemctl status bricklapse-monitor
```

- **Restart a service:**
```sh
sudo systemctl restart bricklapse-server
sudo systemctl restart bricklapse-monitor
```

- **Stop a service:**
```bash
sudo systemctl stop bricklapse-server
sudo systemctl stop bricklapse-monitor
```

- **View logs:**
```sh
journalctl -u bricklapse-server -f
journalctl -u bricklapse-monitor -f
```

# Troubleshooting
For further troubleshooting, check the log files in the main project directory or use `journalctl` as shown above.

- Make sure your Python virtual environment and all dependencies are installed before enabling the services.
- You can adjust the delay by editing the `ExecStartPre` line in `bricklapse-monitor.service`.
- The camera monitor service is configured to start only after the web server is running, with a 10-second delay to ensure the server is ready.









