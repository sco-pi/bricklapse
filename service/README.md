# BrickLapse Service Management

## Files

This directory contains systemd service files and startup scripts for running the Bricklapse application (web server, camera monitor, timelapse encoder, and HID keyboard listener) as Linux services. This allows the application to start automatically on boot, run in the background, and be easily managed.

## Service Files

- `bricklapse-server.service` — systemd unit for the FastAPI web server
- `bricklapse-monitor.service` — systemd unit for the camera monitor script
- `bricklapse-encoder.service` — systemd unit for the timelapse encoder (WebSocket client)
- `bricklapse-keyboard.service` — systemd unit for the HID keyboard listener
- `start_server.sh` — startup script for the web server
- `start_monitor.sh` — startup script for the camera monitor
- `start_encoder.sh` — startup script for the timelapse encoder
- `start_keyboard.sh` — startup script for the keyboard listener


## Installation

1. **Copy service files to systemd directory:**
```sh
sudo cp bricklapse-server.service /etc/systemd/system/
sudo cp bricklapse-monitor.service /etc/systemd/system/
sudo cp bricklapse-encoder.service /etc/systemd/system/
sudo cp bricklapse-keyboard.service /etc/systemd/system/
```

2. **Make sure the startup scripts are executable:**
```sh
chmod +x /home/smurch/BrickLapsePython/service/start_server.sh
chmod +x /home/smurch/BrickLapsePython/service/start_monitor.sh
chmod +x /home/smurch/BrickLapsePython/service/start_encoder.sh
chmod +x /home/smurch/BrickLapsePython/service/start_keyboard.sh
```

3. **Reload systemd to recognize new services:**
```sh
sudo systemctl daemon-reload
```

4. **Enable services to start on boot:**
```sh
sudo systemctl enable bricklapse-server
sudo systemctl enable bricklapse-monitor
sudo systemctl enable bricklapse-encoder
sudo systemctl enable bricklapse-keyboard
```

5. **Start the services:**
```sh
sudo systemctl start bricklapse-server
sudo systemctl start bricklapse-monitor
sudo systemctl start bricklapse-encoder
sudo systemctl start bricklapse-keyboard
```

## Service Management
- **Check status:**

```sh
sudo systemctl status bricklapse-server
sudo systemctl status bricklapse-monitor
sudo systemctl status bricklapse-encoder
sudo systemctl status bricklapse-keyboard
```

- **Restart a service:**
```sh
sudo systemctl restart bricklapse-server
sudo systemctl restart bricklapse-monitor
sudo systemctl restart bricklapse-encoder
sudo systemctl restart bricklapse-keyboard
```

- **Stop a service:**
```bash
sudo systemctl stop bricklapse-server
sudo systemctl stop bricklapse-monitor
sudo systemctl stop bricklapse-encoder
sudo systemctl stop bricklapse-keyboard
```

- **View logs:**
```sh
journalctl -u bricklapse-server -f
journalctl -u bricklapse-monitor -f
journalctl -u bricklapse-encoder -f
journalctl -u bricklapse-keyboard -f
```

## HID Keyboard Listener Configuration

The keyboard listener service monitors for media control key presses and sends navigation commands to the BrickLapse server:

**Key Mappings:**
- **Next Track** → Next page
- **Previous Track** → Previous page
- **Volume Up** → Next instruction (document)
- **Volume Down** → Previous instruction (document)

**Configuration Options:**

You can customize the keyboard listener by editing the environment variables in `bricklapse-keyboard.service`:

```ini
# Server URL (default: http://localhost:8000)
Environment="BRICKLAPSE_SERVER_URL=http://localhost:8000"

# Sets configuration file (default: /home/smurch/BrickLapsePython/sets.yml)
Environment="BRICKLAPSE_SETS_FILE=/home/smurch/BrickLapsePython/sets.yml"

# Optional: Specify exact keyboard device
Environment="KEYBOARD_DEVICE_PATH=/dev/input/event0"

# Optional: Filter by vendor/product ID (in hex)
Environment="KEYBOARD_VENDOR_ID=046d"
Environment="KEYBOARD_PRODUCT_ID=c52b"
```

**Finding Your Keyboard Device:**

To identify your HID keyboard device:

```bash
# List all input devices
ls -la /dev/input/by-id/

# Show device information
python3 -c "from evdev import list_devices, InputDevice; [print(f'{d}: {InputDevice(d).name}') for d in list_devices()]"

# Get vendor/product IDs
lsusb
```

**Permissions:**

The keyboard listener needs access to `/dev/input/` devices. The service runs as root by default. Alternatively, you can:

1. Add your user to the `input` group:
```bash
sudo usermod -a -G input smurch
```

2. Create a udev rule for your specific keyboard in `/etc/udev/rules.d/99-keyboard.rules`:
```
SUBSYSTEM=="input", ATTRS{idVendor}=="046d", ATTRS{idProduct}=="c52b", MODE="0660", GROUP="input"
```

3. Reload udev rules:
```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

# Troubleshooting
For further troubleshooting, check the log files in the main project directory or use `journalctl` as shown above.

- Make sure your Python virtual environment and all dependencies are installed before enabling the services.
- You can adjust the delay by editing the `ExecStartPre` line in the service files.
- The camera monitor service is configured to start only after the web server is running, with a 10-second delay to ensure the server is ready.
- The encoder service is configured to start only after the web server is running, with a 5-second delay. It connects via WebSocket to receive encoding jobs.









