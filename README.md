# Background
Havning recently signed up for [Brick Borrow](https://www.brickborrow.com/) I want to ensure that I capture each build as a timelapse. As part of this I wanted to show current step in the instructions in the background on my Legion Go, however it has a quirk where the display is technically in landscape. As such to mirror it on any other screen so that I could also use the instructions, Windows would helpfully also rotate the mirrored screen. This application is my overengineered solution to that, allowing instructions to be controlled from one browser and others using websockets to stay updated as the main screen moves steps/manuals. I have also attempted to use gphoto2 to capture the timelapse and ffmpeg to convert the captured images into a video.

## Future Improvements/ToDos
- [ ] Support multiple cameras at the same time
- [ ] Add set details page
	- [ ] Store description for Instagram posts
	- [ ] Upload/view photos/vidoes taken outside of timelapse process
	- [ ] Mark/favorite images/videos for a set to preview instagram post and make an easy way to download them
- [ ] Allow multiple encoders to run the service at the same time and allow a user to route an encode to a specific encoder
- [ ] Track the status/progress of encodes and show ETA
- [ ] Move to a SPA framework for the front end

## Timelapse Capture Backends

The timelapse monitor script (`monitor_timelapse_camera.py`) now supports multiple camera backends via a pluggable abstraction:

Supported backends:
- `gphoto2` (default) DSLR/mirrorless via libgphoto2 (event-driven file added events)
- `picamera2` Raspberry Pi Camera using Picamera2 library
- `libcamera` Fallback using `libcamera-still` CLI
- `opencv` Generic V4L2 / USB webcam capture via OpenCV
- `auto` Tries the above in priority order: gphoto2 -> picamera2 -> libcamera -> opencv

Basic usage:
```
python monitor_timelapse_camera.py \
	--api-host http://127.0.0.1:8000 \
	--set-number 42115 \
	--phase build \
	--backend picamera2 \
	--interval 2.0 \
	--resolution 1920x1080
```

Additional optional flags:
```
	--device-index 0          # For opencv backend
	--iso 100                 # Backend specific (picamera2/libcamera)
	--shutter-us 20000        # Shutter speed in microseconds where supported
	--awb auto                # White balance mode (picamera2/libcamera)
	--exposure-mode auto      # Exposure mode (backend specific placeholder)
```

Event-driven vs interval:
- gphoto2 backend waits for camera file-added events.
- All other backends use the provided `--interval` to schedule captures (monotonic clock, low drift).

Monitor status now includes a `backend` field so the server/UI can display which capture path is active.

If you choose `--backend auto`, the script will attempt each backend in priority order until one initializes successfully, reporting any failures in the log.

### Pausing / Resuming Capture

For interval-based (non-gphoto2) backends you can now pause or resume frame acquisition from the control UI using the "Pause Capture" / "Resume Capture" button. This toggles a server-side `capture_enabled` flag exposed at:

- `GET /api/monitor/status`  -> includes `capture_enabled`
- `POST /api/monitor/capture {"enabled": true|false}` -> updates the flag and broadcasts status via websocket.

When paused the monitor script continues sending heartbeat status updates but skips taking new frames until resumed.