#!/bin/bash
cd /home/smurch/BrickLapsePython
source bin/activate

python monitor_timelapse_camera.py --backend picamera2 --interval 1.0 --resolution 1920x1080

#screen -dmS bricklapse-monitor bash -c 'python monitor_timelapse_camera.py'