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


def main():
    locale.setlocale(locale.LC_ALL, '')
    # Init camera
    camera = gp.Camera()
    camera.init()
    timeout = 3000  # milliseconds
    count = INITIAL_COUNT
    # Create the directory if it doesn't exist
    if not os.path.exists(WORK_DIR):
        os.makedirs(WORK_DIR)
    while True:
        try:
            event_type, event_data = camera.wait_for_event(timeout)
            if event_type == gp.GP_EVENT_FILE_ADDED:
                cam_file = camera.file_get(
                    event_data.folder, event_data.name, gp.GP_FILE_TYPE_NORMAL)
                target_path = os.path.join(WORK_DIR, f"frame{count:05d}.jpg")
                print("Image is being saved to {}".format(target_path))
                cam_file.save(target_path)

                # Send update to the server
                update = {
                    "timelapse": {
                        "set_number": SET_NUMBER,
                        "phase": PHASE,
                        "filename": f"frame{count:05d}.jpg",
                        "timestamp": time.time(),
                        "count": count
                    }
                }
                requests.post(f"{API_HOST}/api/update", json=update)

                count += 1
        except KeyboardInterrupt:
            break
    return 0


# Start the main function, taking in command line arguments for api host, set number, phase, and initial count
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-host", type=str, default=API_HOST, help="Host to update with the status of the timelapse")
    parser.add_argument("--set-number", type=str, default="0", help="Set number to capture images for")
    parser.add_argument("--phase", type=str, default="0", help="Phase of the timelapse, e.g. sort, build, or dissasemble")
    parser.add_argument("--initial-count", type=int, default=INITIAL_COUNT, help="Initial number of the captured images")
    args = parser.parse_args()
    API_HOST = args.api_host
    SET_NUMBER = args.set_number
    PHASE = args.phase
    INITIAL_COUNT = args.initial_count

    # If setnumber or phase is 0 set details from the API /api/status endpoint
    if SET_NUMBER == "0" or PHASE == "0":
        status = requests.get(f"{API_HOST}/api/status")
        if status.status_code == 200:
            data = status.json()
            if SET_NUMBER == "0":
                SET_NUMBER = data["set"]
            if PHASE == "0":
                PHASE = data["phase"]
        else:
            print("Error getting status from the API")
            sys.exit(1)

    WORK_DIR = f"/mnt/legotimelapse/captures/{SET_NUMBER}/{PHASE}"
    print(f"Starting capture for set {SET_NUMBER} in phase {PHASE} starting at {INITIAL_COUNT}")

    sys.exit(main())
