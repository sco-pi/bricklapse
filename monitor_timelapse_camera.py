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

import gphoto2 as gp

# Host to update with the status of the timelapse
API_HOST = "http://127.0.0.1:8000"
# Set number to capture images for
SET_NUMBER = "42115"
# Phase of the timelapse
PHASE = "build"
# Initial number of the captured images
INITIAL_COUNT = 0
# time between captures
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


def capture_loop(camera, count, stop_event, status_change_event):
    """
    Main camera capture loop that handles image capture events.
    Returns when stop_event is set or status_change_event is set.
    """
    timeout = 3000  # milliseconds
    
    # Create the directory if it doesn't exist
    if not os.path.exists(WORK_DIR):
        os.makedirs(WORK_DIR)
        logger.info(f"Created directory {WORK_DIR}")

    logger.info(f"Starting capture loop for {SET_NUMBER}/{PHASE} from count {count}")
    
    # Update monitor status to show we're actively capturing
    update_monitor_status(API_HOST, {
        "running": True,
        "camera_connected": True,
        "current_set": SET_NUMBER,
        "current_phase": PHASE,
        "capture_count": count,
        "errors": []
    })
    
    # Track errors for status reporting
    recent_errors = []
    last_status_update = time.time()
    status_update_interval = 10  # seconds
    
    while not (stop_event.is_set() or status_change_event.is_set()):
        try:
            event_type, event_data = camera.wait_for_event(timeout)
            
            if event_type == gp.GP_EVENT_FILE_ADDED:
                try:
                    cam_file = camera.file_get(
                        event_data.folder, event_data.name, gp.GP_FILE_TYPE_NORMAL)
                    target_path = os.path.join(WORK_DIR, f"frame{count:05d}.jpg")
                    logger.info(f"Image is being saved to {target_path}")
                    cam_file.save(target_path)
                    
                    current_time = time.time()

                    # Send update to the server
                    update = {
                        "timelapse": {
                            "set_number": SET_NUMBER,
                            "phase": PHASE,
                            "filename": f"frame{count:05d}.jpg",
                            "timestamp": current_time,
                            "count": count
                        }
                    }
                    try:
                        response = requests.post(f"{API_HOST}/api/update", json=update, timeout=5)
                        if response.status_code != 200:
                            logger.warning(f"Failed to update server: HTTP {response.status_code}")
                            recent_errors.append(f"Failed server update: HTTP {response.status_code}")
                    except requests.RequestException as e:
                        logger.warning(f"Error updating server: {e}")
                        recent_errors.append(f"Server communication error: {str(e)}")

                    # Update monitor status after capture
                    update_monitor_status(API_HOST, {
                        "running": True, 
                        "camera_connected": True,
                        "last_capture": current_time,
                        "current_set": SET_NUMBER,
                        "current_phase": PHASE,
                        "capture_count": count,
                        "errors": recent_errors[-5:] if recent_errors else []  # Keep only the 5 most recent errors
                    })
                    recent_errors = []  # Clear errors after successful update

                    count += 1
                except gp.GPhoto2Error as e:
                    error_msg = f"Error processing camera file: {e}"
                    logger.error(error_msg)
                    recent_errors.append(error_msg)
            
            elif event_type == gp.GP_EVENT_TIMEOUT:
                # Just a timeout, continue the loop
                pass
                
            # Periodically update status even if no new captures
            if time.time() - last_status_update > status_update_interval:
                update_monitor_status(API_HOST, {
                    "running": True,
                    "camera_connected": True,
                    "current_set": SET_NUMBER,
                    "current_phase": PHASE,
                    "capture_count": count,
                    "errors": recent_errors[-5:] if recent_errors else []
                })
                last_status_update = time.time()
                
        except gp.GPhoto2Error as e:
            error_msg = f"Camera error in capture loop: {e}"
            logger.error(error_msg)
            update_monitor_status(API_HOST, {
                "running": True,
                "camera_connected": False,
                "errors": [error_msg]
            })
            return False
        except Exception as e:
            error_msg = f"Unexpected error in capture loop: {e}"
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            update_monitor_status(API_HOST, {
                "running": True,
                "camera_connected": False,
                "errors": [error_msg]
            })
            return False
    
    return True


def main():
    locale.setlocale(locale.LC_ALL, '')
    
    global WORK_DIR
    
    # Event to signal a graceful shutdown
    stop_event = threading.Event()
    
    # Event to signal that the set or phase has changed
    status_change_event = threading.Event()
    
    # Shared reference for the current set and phase
    current_set_phase = [SET_NUMBER, PHASE]
    
    # Update the monitor status to show we're starting up
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
            # Initialize camera
            camera = initialize_camera()
            if not camera:
                logger.error("Failed to initialize camera, waiting before retry...")
                # Update status to show camera connection failed
                update_monitor_status(API_HOST, {
                    "running": True,
                    "camera_connected": False,
                    "errors": ["Failed to initialize camera, retrying..."]
                })
                time.sleep(RETRY_DELAY * 2)
                continue
                
            # Get the count for the current directory
            count = get_last_file_number(WORK_DIR)
            
            # Clear any pending status change events
            status_change_event.clear()
            
            # Update status to show successful camera connection
            update_monitor_status(API_HOST, {
                "running": True,
                "camera_connected": True,
                "current_set": SET_NUMBER,
                "current_phase": PHASE,
                "capture_count": count
            })
            
            # Enter the capture loop
            success = capture_loop(camera, count, stop_event, status_change_event)
            
            if status_change_event.is_set():
                logger.info(f"Set/phase changed to {SET_NUMBER}/{PHASE}, restarting capture")
                
                # Update the work directory
                WORK_DIR = f"/mnt/legotimelapse/captures/{SET_NUMBER}/{PHASE}"
                
                # Update status to show phase/set change
                update_monitor_status(API_HOST, {
                    "running": True,
                    "camera_connected": True,
                    "current_set": SET_NUMBER,
                    "current_phase": PHASE
                })
                
                # Close the camera to reinitialize with clean state
                try:
                    camera.exit()
                    logger.info("Camera exited cleanly")
                except Exception as e:
                    logger.warning(f"Error closing camera: {e}")
            
            elif not success:
                logger.warning("Capture loop failed, will reinitialize")
                # Update status to show failure
                update_monitor_status(API_HOST, {
                    "running": True,
                    "camera_connected": False,
                    "errors": ["Capture loop failed, reinitializing..."]
                })
                time.sleep(RETRY_DELAY)
                
                # Try to clean up the camera
                try:
                    camera.exit()
                except:
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

    logger.info(f"Starting capture for set {SET_NUMBER} in phase {PHASE} starting at {INITIAL_COUNT}")
    logger.info(f"Status check interval: {STATUS_CHECK_INTERVAL}s, Retry delay: {RETRY_DELAY}s")

    try:
        exit_code = main()
        logger.info(f"Exiting with code {exit_code}")
        sys.exit(exit_code)
    except Exception as e:
        logger.critical(f"Unhandled exception: {e}")
        logger.critical(traceback.format_exc())
        sys.exit(1)
