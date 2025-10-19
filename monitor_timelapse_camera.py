#!/usr/bin/env python

# python-gphoto2 - Python interface to libgphoto2
# http://github.com/jim-easterbrook/python-gphoto2
# Copyright (C) 2019  Göktuğ Başaran
#
# This file is part of python-gphoto2.
#
# python-gphoto2 is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# python-gphoto2 is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with python-gphoto2.  If not, see
# <https://www.gnu.org/licenses/>.

# *******************************************************
# camera.wait_for_event() function waits for a capture trigger
# to arrive and returns the folder and name of the new file.
# When it does, camera.file_get() is used to download
# the image directly from the camera, without using SD
# card
#
# camera.trigger_capture() or Trigger Button on the
# camera can be used to start capturing.
#
# gp_capture_image_and_download() method takes about 2 seconds
# to process since it saves the image to SD CARD
# first then downloads it, which takes a lot of time.
# *******************************************************

# Additional comment by Jim Easterbrook: My cameras save to SD card or
# RAM according to the capture target setting. Use of
# camera.wait_for_event() or camera.capture() makes no difference to
# where the image is saved.

import locale
import os
import sys
import time
import requests
import argparse
import glob
import re
import threading
import logging
from datetime import datetime
import traceback

import gphoto2 as gp  # kept for legacy direct references; backend abstraction now used
from timelapse_backends import (
    BackendConfig,
    BackendError,
    create_backend,
    BaseTimelapseCamera,
)

# Host to update with the status of the timelapse
API_HOST = "http://127.0.0.1:8000"
# Set number to capture images for
SET_NUMBER = "42115"
# Phase of the timelapse
PHASE = "build"
# Initial number of the captured images
INITIAL_COUNT = 0
# time between captures (used for non event-driven backends)
INTERVAL = 1.0
# temporary directory
WORK_DIR = f"/mnt/legotimelapse/captures/{SET_NUMBER}/{PHASE}"
# result
OUT_FILE = 'time_lapse.mp4'
# Time to wait between status checks (seconds)
STATUS_CHECK_INTERVAL = 10
# Maximum number of retries for camera initialization
MAX_RETRIES = 5
# Time to wait between retries (seconds)
RETRY_DELAY = 5

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(f"monitor_timelapse_camera_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    ]
)
logger = logging.getLogger('timelapse_monitor')

def update_monitor_status(api_host, status_data):
    """
    Send status update to the server.
    """
    try:
        response = requests.post(
            f"{api_host}/api/monitor/update",
            json=status_data,
            timeout=5
        )
        if response.status_code != 200:
            logger.warning(f"Failed to update monitor status: HTTP {response.status_code}")
        return response.status_code == 200
    except requests.RequestException as e:
        logger.warning(f"Error updating monitor status: {e}")
        return False


def get_current_status(api_host):
    """
    Fetch the current set and phase from the API.
    Returns tuple (set_number, phase) or None on failure
    """
    try:
        response = requests.get(f"{api_host}/api/status", timeout=5)
        if response.status_code == 200:
            data = response.json()
            return (data["set"], data["phase"])
        else:
            logger.error(f"Failed to get status from API: HTTP {response.status_code}")
            return None
    except requests.RequestException as e:
        logger.error(f"Error getting status from API: {e}")
        return None


def initialize_camera():
    """
    Initialize the camera with retry logic.
    Returns camera object or None if initialization fails.
    """
    retries = 0
    while retries < MAX_RETRIES:
        try:
            logger.info("Attempting to initialize camera...")
            camera = gp.Camera()
            camera.init()
            logger.info("Camera initialized successfully")
            return camera
        except gp.GPhoto2Error as e:
            retries += 1
            logger.error(f"Failed to initialize camera (attempt {retries}/{MAX_RETRIES}): {e}")
            if retries < MAX_RETRIES:
                logger.info(f"Retrying in {RETRY_DELAY} seconds...")
                time.sleep(RETRY_DELAY)
            else:
                logger.error("Max retries reached. Could not initialize camera.")
                return None

def get_last_file_number(directory, file_pattern="*.jpg"):
    """Find the highest numbered file in the directory and return the next number."""
    try:
        files = glob.glob(os.path.join(directory, file_pattern))
        if not files:
            logger.info(f"No files found in {directory}, starting with initial count {INITIAL_COUNT}")
            return INITIAL_COUNT # No files found, start with the initial count
            
        # Extract numbers from filenames using regex
        numbers = []
        for file in files:
            filename = os.path.basename(file)
            match = re.search(r'(\d+)', filename)
            if match:
                numbers.append(int(match.group(1)))
                
        # Debug print the count of the files
        next_count = max(numbers) + 1 if numbers else INITIAL_COUNT
        logger.info(f"Found {len(numbers)} files in the directory, next count: {next_count}")
        
        return next_count
    except Exception as e:
        logger.error(f"Error detecting last file number: {e}")
        return INITIAL_COUNT  # Default to initial count if there is an error


def status_monitor(stop_event, status_change_event, current_set_phase):
    """
    Thread function to periodically check for status changes.
    Sets status_change_event when set or phase changes.
    """
    global SET_NUMBER, PHASE, WORK_DIR
    
    while not stop_event.is_set():
        try:
            current_status = get_current_status(API_HOST)
            if current_status:
                new_set, new_phase = current_status
                
                # Check if set or phase has changed
                if new_set != current_set_phase[0] or new_phase != current_set_phase[1]:
                    logger.info(f"Status change detected: {current_set_phase[0]}/{current_set_phase[1]} -> {new_set}/{new_phase}")
                    
                    # Update the global variables
                    SET_NUMBER = new_set
                    PHASE = new_phase
                    WORK_DIR = f"/mnt/legotimelapse/captures/{SET_NUMBER}/{PHASE}"
                    
                    # Update the shared reference
                    current_set_phase[0] = new_set
                    current_set_phase[1] = new_phase
                    
                    # Signal the main thread about the change
                    status_change_event.set()
            
            # Sleep for the configured interval
            for _ in range(STATUS_CHECK_INTERVAL):
                if stop_event.is_set():
                    break
                time.sleep(1)
        
        except Exception as e:
            logger.error(f"Error in status monitor: {e}")
            time.sleep(RETRY_DELAY)


CAPTURE_ENABLED = True  # global flag controlled by server (polled)

def _poll_capture_enabled():
    global CAPTURE_ENABLED
    try:
        resp = requests.get(f"{API_HOST}/api/monitor/status", timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            if "capture_enabled" in data:
                CAPTURE_ENABLED = bool(data["capture_enabled"])
    except Exception:
        pass

def capture_loop_backend(backend: BaseTimelapseCamera, count: int, stop_event, status_change_event):
    """Unified capture loop supporting event-driven and interval-driven backends."""
    # Create directory
    if not os.path.exists(WORK_DIR):
        os.makedirs(WORK_DIR)
        logger.info(f"Created directory {WORK_DIR}")

    logger.info(f"Starting capture loop ({backend.name}) for {SET_NUMBER}/{PHASE} from count {count}")

    # Initial status
    update_monitor_status(API_HOST, {
        "running": True,
        "camera_connected": True,
        "current_set": SET_NUMBER,
        "current_phase": PHASE,
        "capture_count": count,
        "backend": backend.name,
        "errors": []
    })

    recent_errors = []
    last_status_update = time.time()
    status_update_interval = 10
    interval = INTERVAL if not backend.event_driven else None
    next_capture_time = time.monotonic() + (interval if interval else 0)
    last_capture_mono = None  # monotonic timestamp of last successful capture
    prev_capture_enabled = CAPTURE_ENABLED

    timeout_ms = 3000

    poll_interval = 5  # seconds for capture_enabled polling
    last_poll = 0

    while not (stop_event.is_set() or status_change_event.is_set()):
        try:
            now = time.time()
            if now - last_poll > poll_interval:
                _poll_capture_enabled()
                last_poll = now

            # Detect transition from paused -> resumed for interval backends
            if not backend.event_driven and prev_capture_enabled is False and CAPTURE_ENABLED is True:
                next_capture_time = time.monotonic() + interval
                logger.info(f"Resume detected; scheduling next capture at {next_capture_time:.3f} (+{interval}s)")
            prev_capture_enabled = CAPTURE_ENABLED

            if not CAPTURE_ENABLED:
                # When paused, still provide heartbeat updates periodically (without overriding capture_enabled)
                if time.time() - last_status_update > status_update_interval:
                    update_monitor_status(API_HOST, {
                        "running": True,
                        "camera_connected": True,
                        "current_set": SET_NUMBER,
                        "current_phase": PHASE,
                        "capture_count": count,
                        "backend": backend.name,
                        "errors": []
                    })
                    last_status_update = time.time()
                time.sleep(0.2)
                continue
            if backend.event_driven:
                event = backend.wait_for_event(timeout_ms)
                # event is a tuple (event_type, event_data)
                if isinstance(event, tuple) and len(event) == 2:
                    event_type, _ = event
                    if event_type == gp.GP_EVENT_FILE_ADDED:  # type: ignore
                        target_path = os.path.join(WORK_DIR, f"frame{count:05d}.jpg")
                        if backend.handle_event(event, target_path):
                            current_time = time.time()
                            _post_capture_status(count, current_time, recent_errors, backend)
                            count += 1
                            recent_errors = []
                # else ignore other events / timeouts
            else:
                now_mono = time.monotonic()
                # Prevent burst if we are too far behind (e.g., long pause without reset)
                behind = now_mono - next_capture_time
                if behind > interval * 3:  # arbitrarily choose 3x interval as stale threshold
                    logger.info(f"Behind by {behind:.3f}s (>3x interval); resetting schedule")
                    next_capture_time = now_mono

                if now_mono >= next_capture_time:
                    target_path = os.path.join(WORK_DIR, f"frame{count:05d}.jpg")
                    ok = backend.capture_next(target_path)
                    current_time = time.time()
                    if ok:
                        _post_capture_status(count, current_time, recent_errors, backend)
                        # Interval drift / rate logging
                        if last_capture_mono is not None:
                            delta = now_mono - last_capture_mono
                            if delta < interval * 0.7:
                                logger.warning(f"Capture interval too short: {delta:.3f}s (expected ~{interval}s)")
                            elif delta > interval * 1.5:
                                logger.warning(f"Capture interval too long: {delta:.3f}s (expected ~{interval}s)")
                            else:
                                logger.debug(f"Capture interval OK: {delta:.3f}s")
                        last_capture_mono = now_mono
                        count += 1
                        recent_errors = []
                    else:
                        recent_errors.append("capture failed")
                    # schedule next capture using fixed step to avoid drift
                    next_capture_time += interval
                else:
                    # sleep a short amount to avoid busy wait
                    time.sleep(0.05)

            # Periodic status update
            if time.time() - last_status_update > status_update_interval:
                update_monitor_status(API_HOST, {
                    "running": True,
                    "camera_connected": True,
                    "current_set": SET_NUMBER,
                    "current_phase": PHASE,
                    "capture_count": count,
                    "backend": backend.name,
                    "errors": recent_errors[-5:] if recent_errors else []
                })
                last_status_update = time.time()

        except BackendError as be:
            err = f"Backend error: {be}"
            logger.error(err)
            update_monitor_status(API_HOST, {
                "running": True,
                "camera_connected": False,
                "backend": backend.name,
                "errors": [err]
            })
            return False
        except gp.GPhoto2Error as e:
            err = f"Camera error (gphoto2): {e}"
            logger.error(err)
            update_monitor_status(API_HOST, {
                "running": True,
                "camera_connected": False,
                "backend": backend.name,
                "errors": [err]
            })
            return False
        except Exception as e:
            err = f"Unexpected capture loop error: {e}"
            logger.error(err)
            logger.error(traceback.format_exc())
            update_monitor_status(API_HOST, {
                "running": True,
                "camera_connected": False,
                "backend": backend.name,
                "errors": [err]
            })
            return False
    return True


def _post_capture_status(count: int, current_time: float, recent_errors, backend: BaseTimelapseCamera):
    """Helper to send update after a successful frame capture."""
    filename = f"frame{count:05d}.jpg"
    update_payload = {
        "timelapse": {
            "set_number": SET_NUMBER,
            "phase": PHASE,
            "filename": filename,
            "timestamp": current_time,
            "count": count
        }
    }
    try:
        response = requests.post(f"{API_HOST}/api/update", json=update_payload, timeout=5)
        if response.status_code != 200:
            logger.warning(f"Failed to update server: HTTP {response.status_code}")
            recent_errors.append(f"Failed server update: HTTP {response.status_code}")
    except requests.RequestException as e:
        logger.warning(f"Error updating server: {e}")
        recent_errors.append(f"Server communication error: {str(e)}")

    # NOTE: Do NOT include capture_enabled here so user-driven toggle on server is preserved.
    update_monitor_status(API_HOST, {
        "running": True,
        "camera_connected": True,
        "last_capture": current_time,
        "current_set": SET_NUMBER,
        "current_phase": PHASE,
        "capture_count": count,
        "backend": backend.name,
        "errors": recent_errors[-5:] if recent_errors else []
    })


def main(backend_name: str, backend_cfg: BackendConfig):
    locale.setlocale(locale.LC_ALL, '')
    
    global WORK_DIR
    
    # Event to signal a graceful shutdown
    stop_event = threading.Event()
    
    # Event to signal that the set or phase has changed
    status_change_event = threading.Event()
    
    # Shared reference for the current set and phase
    current_set_phase = [SET_NUMBER, PHASE]
    
    # Update the monitor status to show we're starting up
    # Initial status (do not set capture_enabled here; server owns that flag)
    update_monitor_status(API_HOST, {
        "running": True,
        "camera_connected": False,
        "current_set": SET_NUMBER,
        "current_phase": PHASE,
        "capture_count": 0,
        "errors": []
    })
    
    try:
        # Start the status monitor thread
        monitor_thread = threading.Thread(
            target=status_monitor,
            args=(stop_event, status_change_event, current_set_phase),
            daemon=True
        )
        monitor_thread.start()
        logger.info("Status monitor thread started")
        
        while not stop_event.is_set():
            # Initialize backend
            try:
                backend = create_backend(backend_name, backend_cfg)
                backend.ensure_initialized()
            except BackendError as be:
                logger.error(f"Backend initialization failed: {be}")
                update_monitor_status(API_HOST, {
                    "running": True,
                    "camera_connected": False,
                    "backend": backend_name,
                    "errors": [f"Backend init failed: {be}"]
                })
                time.sleep(RETRY_DELAY * 2)
                continue

            count = get_last_file_number(WORK_DIR)
            status_change_event.clear()

            success = capture_loop_backend(backend, count, stop_event, status_change_event)

            if status_change_event.is_set():
                logger.info(f"Set/phase changed to {SET_NUMBER}/{PHASE}, restarting capture")
                WORK_DIR = f"/mnt/legotimelapse/captures/{SET_NUMBER}/{PHASE}"
                update_monitor_status(API_HOST, {
                    "running": True,
                    "camera_connected": True,
                    "backend": backend.name,
                    "current_set": SET_NUMBER,
                    "current_phase": PHASE
                })
                try:
                    backend.shutdown()
                except Exception as e:
                    logger.warning(f"Error shutting down backend: {e}")
            elif not success:
                logger.warning("Capture loop failed, will reinitialize backend")
                update_monitor_status(API_HOST, {
                    "running": True,
                    "camera_connected": False,
                    "backend": backend.name,
                    "errors": ["Capture loop failed, reinitializing..."]
                })
                time.sleep(RETRY_DELAY)
                try:
                    backend.shutdown()
                except Exception:
                    pass
            
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, shutting down...")
    except Exception as e:
        logger.error(f"Unexpected error in main: {e}")
        logger.error(traceback.format_exc())
        # Update status with critical error
        update_monitor_status(API_HOST, {
            "running": False,
            "camera_connected": False,
            "errors": [f"Critical error: {str(e)}"]
        })
    finally:
        # Update status to show we're shutting down
        update_monitor_status(API_HOST, {
            "running": False,
            "camera_connected": False
        })
        stop_event.set()
        monitor_thread.join(timeout=5)
        logger.info("Monitor thread joined")
        
    return 0


# Start the main function, taking in command line arguments for api host, set number, phase, and initial count
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-host", type=str, default=API_HOST, help="Host to update with the status of the timelapse")
    parser.add_argument("--set-number", type=str, default="0", help="Set number to capture images for")
    parser.add_argument("--phase", type=str, default="0", help="Phase of the timelapse, e.g. sort, build, or dissasemble")
    parser.add_argument("--initial-count", type=int, default=INITIAL_COUNT, help="Initial number of the captured images")
    parser.add_argument("--backend", type=str, default="gphoto2", help="Camera backend: gphoto2|picamera2|libcamera|opencv|auto")
    parser.add_argument("--interval", type=float, default=INTERVAL, help="Capture interval seconds (non event-driven backends)")
    parser.add_argument("--resolution", type=str, default=None, help="Resolution WxH (e.g. 1920x1080) for supported backends")
    parser.add_argument("--device-index", type=int, default=0, help="Video device index for OpenCV backend")
    parser.add_argument("--iso", type=int, default=None, help="ISO / gain (backend specific)")
    parser.add_argument("--shutter-us", type=int, default=None, help="Shutter speed microseconds (backend specific)")
    parser.add_argument("--awb", type=str, default=None, help="Auto white balance mode (backend specific)")
    parser.add_argument("--exposure-mode", type=str, default=None, help="Exposure mode (backend specific)")
    parser.add_argument("--status-check-interval", type=int, default=STATUS_CHECK_INTERVAL, 
                        help="Seconds between checking for status changes")
    parser.add_argument("--retry-delay", type=int, default=RETRY_DELAY,
                        help="Seconds to wait between camera initialization retries")
    
    args = parser.parse_args()
    API_HOST = args.api_host
    SET_NUMBER = args.set_number
    PHASE = args.phase
    STATUS_CHECK_INTERVAL = args.status_check_interval
    RETRY_DELAY = args.retry_delay
    
    # If using auto-detect for initial count, we need to determine the correct directory first
    if SET_NUMBER == "0" or PHASE == "0":
        try:
            status = requests.get(f"{API_HOST}/api/status", timeout=5)
            if status.status_code == 200:
                data = status.json()
                if SET_NUMBER == "0":
                    SET_NUMBER = data["set"]
                if PHASE == "0":
                    PHASE = data["phase"]
            else:
                logger.error(f"Error getting status from the API: HTTP {status.status_code}")
                sys.exit(1)
        except requests.RequestException as e:
            logger.error(f"Error getting status from the API: {e}")
            sys.exit(1)
            
    # Update the work directory based on set and phase
    WORK_DIR = f"/mnt/legotimelapse/captures/{SET_NUMBER}/{PHASE}"
    
    # Now determine initial count if auto-detect was requested
    if args.initial_count == -1:
        INITIAL_COUNT = get_last_file_number(WORK_DIR)
    else:
        INITIAL_COUNT = args.initial_count

    # Parse resolution
    res_tuple = None
    if args.resolution:
        try:
            w, h = args.resolution.lower().split("x")
            res_tuple = (int(w), int(h))
        except Exception:
            logger.error("Invalid --resolution format, expected WxH")
            sys.exit(1)

    # Update interval global (used by capture loop)
    INTERVAL = args.interval

    backend_cfg = BackendConfig(
        interval=args.interval,
        resolution=res_tuple,
        device_index=args.device_index,
        exposure_mode=args.exposure_mode,
        awb=args.awb,
        iso=args.iso,
        shutter_us=args.shutter_us,
    )

    logger.info(f"Starting capture for set {SET_NUMBER} in phase {PHASE} starting at {INITIAL_COUNT} using backend {args.backend}")
    logger.info(f"Status check interval: {STATUS_CHECK_INTERVAL}s, Retry delay: {RETRY_DELAY}s, Interval: {INTERVAL}s")

    try:
        exit_code = main(args.backend, backend_cfg)
        logger.info(f"Exiting with code {exit_code}")
        sys.exit(exit_code)
    except Exception as e:
        logger.critical(f"Unhandled exception: {e}")
        logger.critical(traceback.format_exc())
        sys.exit(1)
