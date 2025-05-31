#!/bin/bash
cd /home/smurch/BrickLapsePython
source bin/activate

python monitor_timelapse_camera.py

#screen -dmS bricklapse-monitor bash -c 'python monitor_timelapse_camera.py'