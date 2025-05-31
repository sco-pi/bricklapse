#!/bin/bash
cd /home/smurch/BrickLapsePython
source bin/activate

uvicorn server:app --host 0.0.0.0 --port 8000 --reload

#screen -dmS bricklapse-server bash -c 'uvicorn server:app --host 0.0.0.0 --port 8000 --reload'