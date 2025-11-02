#!/bin/bash
# Start script for BrickLapse Keyboard Listener Service

cd /home/smurch/BrickLapsePython
source bin/activate
exec python keyboard_listener.py
