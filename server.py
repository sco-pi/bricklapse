from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse
from typing import List
import yaml
import shutil
import os
import json
import time
import gphoto2 as gp
import subprocess
import cv2
import threading
import io
from typing import Optional
from capture_manager import CameraCaptureManager, CameraCaptureError

# Global singleton manager to persist Picamera2 instance
captureManager = CameraCaptureManager(test_image_path="/tmp/pi_test_image.jpg")
try:
    from picamera2 import Picamera2  # Provided by python3-picamera2 package
    from PIL import Image
    _PICAMERA2_AVAILABLE = True
except Exception:  # Pillow or picamera2 may not be installed in venv though system package present
    _PICAMERA2_AVAILABLE = False
    Picamera2 = None  # type: ignore
    Image = None  # type: ignore

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/media", StaticFiles(directory="/mnt/legotimelapse/media"), name="media")

instructions_dir = "/mnt/legotimelapse/instructions"
last_page = 1
last_document = "/instructions/42158/6501852" # Defaults to the Mars Rover set, need to find a better way to default
last_set = "42158"
last_phase = "build"

# Camera monitor status tracking
camera_monitor_status = {
    "running": False,
    "camera_connected": False,
    "last_update": None,
    "last_capture": None,
    "current_set": None,
    "current_phase": None,
    "capture_count": 0,
    "errors": [],
    "backend": None,
    "capture_enabled": False  # new field allowing UI to pause/resume capture
}

templates = Jinja2Templates(directory="templates")

# Create websocket manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
    
    async def broadcast(self, data: str):
        for connection in self.active_connections:
            await connection.send_text(data)

manager = ConnectionManager()

# Function for sending updates to the websocket on page/document changes
async def sendDocumentUpdate(page, document, client_id):
    await manager.broadcast(f'{{"instructions": {{"page": {page}, "document": "{document}"}}, "client_id": "{client_id}"}}')

@app.get("/favicon.ico", include_in_schema=False)
async def get_favicon():
    return FileResponse("static/favicon.ico")

# Default UI Linking to Control, Viewer, and WS Log UIs
@app.get("/", include_in_schema=False)
async def get():
    return FileResponse("templates/control.html")

@app.get("/control", include_in_schema=False)
async def get():
    return FileResponse("templates/control.html")

# Viewer UI
@app.get("/viewer", include_in_schema=False)
async def get():
    return FileResponse("templates/viewer.html")

# Sets UI
@app.get("/sets", include_in_schema=False)
async def get():
    return FileResponse("templates/sets.html")

# Active Set UI
@app.get("/active-set", include_in_schema=False)
async def get():
    return FileResponse("templates/active_set.html")

# Temp Chat UI to test websocket connection
@app.get("/wslog", include_in_schema=False)
async def get():
    return FileResponse("templates/wslog.html")

# Get Image UI
@app.get("/images", include_in_schema=False)
async def get():
    return FileResponse("templates/imageview.html")

# Camera Test UI
@app.get("/camera-test", include_in_schema=False)
async def get():
    return FileResponse("templates/camera_test.html")

# Get specified timelape image for set number and phase
@app.get("/timelapse/{set_number}/{phase}/{filename}")
async def get(set_number: str, phase: str, filename: str):
    return FileResponse(f"/mnt/legotimelapse/captures/{set_number}/{phase}/{filename}")


# Return PDFs from instructions directory based on set number and instruction number
@app.get("/instructions/{set_number}/{instruction_number}")
async def read_item(set_number: str, instruction_number: str):
    return FileResponse(f"{instructions_dir}/{set_number}/{instruction_number}.pdf")

# Save PDF to instructions directory based on set number only, getting the instruction number from the filename
@app.post("/instructions/{set_number}")
async def create_item(set_number: str, pdf: UploadFile = File(...)):
    # Create parent directory if it doesn't exist
    os.makedirs(f"{instructions_dir}/{set_number}", exist_ok=True)
    # Save PDF to instructions directory
    with open(f"{instructions_dir}/{set_number}/{pdf.filename}", "wb") as buffer:
        shutil.copyfileobj(pdf.file, buffer)
    # Get instruction number from filename
    instruction_number = pdf.filename.split(".")[0]
    # Add instruction to sets.yml
    with open("sets.yml", "r") as f:
        sets = yaml.safe_load(f)
        for lego_set in sets['sets']:
            if lego_set['id'] == set_number:
                lego_set['instructions'].append(instruction_number)
    with open("sets.yml", "w") as fw:
        yaml.dump(sets, fw)
    return {"filename": pdf.filename}

# List sets in sets.yml and return as JSON
@app.get("/api/sets")
async def get():
    # Read sets.yml
    with open("sets.yml", "r") as f:
        sets = yaml.safe_load(f)
        return sets
    
# List set by id in sets.yml and return as JSON
@app.get("/api/sets/{set_id}")
async def get(set_id: int):
    # Read sets.yml
    with open("sets.yml", "r") as f:
        sets = yaml.safe_load(f)
        # Loop through sets and return set by id
        for set in sets:
            if set["id"] == set_id:
                return set

# Delete set by id in sets.yml
@app.delete("/api/sets/{set_id}")
async def delete(set_id: str):
    # Read sets.yml
    with open("sets.yml", "r") as f:
        sets = yaml.safe_load(f)
    # Loop through sets and delete set by id
    for lego_set in sets['sets']:
        if lego_set["id"] == set_id:
            sets['sets'].remove(lego_set)
    # Write updated sets.yml
    with open("sets.yml", "w") as f:
        yaml.dump(sets, f)
    return {"message": "Set deleted"}

# Create set in sets.yml
@app.post("/api/sets")
async def create(set: dict):
    # Read sets.yml
    with open("sets.yml", "r") as f:
        sets = yaml.safe_load(f)
    # Append new set to sets
    sets['sets'].append(set)
    # Write updated sets.yml
    with open("sets.yml", "w") as f:
        yaml.dump(sets, f)
    return set

# Update set by id in sets.yml
@app.put("/api/sets/{set_id}")
async def update(set_id: int, set: dict):
    # Read sets.yml
    with open("sets.yml", "r") as f:
        sets = yaml.safe_load(f)
    # Loop through sets and update set by id
    for s in sets:
        if s["id"] == set_id:
            s.update(set)
    # Write updated sets.yml
    with open("sets.yml", "w") as f:
        yaml.dump(sets, f)
    return set

# List media for a set (timelapses, photos, hero images)
@app.get("/api/sets/{set_id}/media")
async def get_set_media(set_id: str):
    """Get all media associated with a set.
    
    Returns:
        {
            "set_id": str,
            "timelapses": [{"phase": str, "filename": str, "url": str, "size_bytes": int, "modified": float}, ...],
            "photos": [{"filename": str, "url": str, "size_bytes": int, "modified": float}, ...],
            "videos": [{"filename": str, "url": str, "size_bytes": int, "modified": float}, ...],
            "hero_image": {"filename": str, "url": str, "size_bytes": int} or None
        }
    """
    base_dir = "/mnt/legotimelapse"
    timelapse_dir = os.path.join(base_dir, "media", set_id, "timelapse")
    photos_dir = os.path.join(base_dir, "media", set_id, "photos")
    videos_dir = os.path.join(base_dir, "media", set_id, "videos")
    media_dir = os.path.join(base_dir, "media", set_id)
    
    result = {
        "set_id": set_id,
        "timelapses": [],
        "photos": [],
        "videos": [],
        "hero_image": None
    }
    
    # Scan for hero image
    hero_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
    for ext in hero_extensions:
        hero_path = os.path.join(media_dir, f"hero{ext}")
        if os.path.exists(hero_path):
            try:
                stat_info = os.stat(hero_path)
                result["hero_image"] = {
                    "filename": f"hero{ext}",
                    "url": f"/media/{set_id}/hero{ext}",
                    "size_bytes": stat_info.st_size
                }
                break
            except Exception as e:
                print(f"[WARN] Could not stat hero image {hero_path}: {e}")
    
    # Scan timelapse directory for mp4 files
    if os.path.exists(timelapse_dir) and os.path.isdir(timelapse_dir):
        for filename in sorted(os.listdir(timelapse_dir)):
            if filename.lower().endswith('.mp4'):
                file_path = os.path.join(timelapse_dir, filename)
                try:
                    stat_info = os.stat(file_path)
                    # Extract phase from filename pattern: "<set_id> - <name> - <phase>.mp4"
                    phase = "unknown"
                    parts = filename.rsplit(' - ', 1)
                    if len(parts) == 2:
                        phase_with_ext = parts[1]
                        phase = phase_with_ext.replace('.mp4', '').replace('-temp', '')
                    
                    result["timelapses"].append({
                        "phase": phase,
                        "filename": filename,
                        "url": f"/media/{set_id}/timelapse/{filename}",
                        "size_bytes": stat_info.st_size,
                        "modified": stat_info.st_mtime
                    })
                except Exception as e:
                    print(f"[WARN] Could not stat {file_path}: {e}")
    # Scan photos directory
    photo_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
    if os.path.exists(photos_dir) and os.path.isdir(photos_dir):
        for filename in sorted(os.listdir(photos_dir)):
            if os.path.splitext(filename)[1].lower() in photo_extensions:
                file_path = os.path.join(photos_dir, filename)
                try:
                    stat_info = os.stat(file_path)
                    result["photos"].append({
                        "filename": filename,
                        "url": f"/media/{set_id}/photos/{filename}",
                        "size_bytes": stat_info.st_size,
                        "modified": stat_info.st_mtime
                    })
                except Exception as e:
                    print(f"[WARN] Could not stat {file_path}: {e}")
    
    # Scan videos directory
    video_extensions = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}
    if os.path.exists(videos_dir) and os.path.isdir(videos_dir):
        for filename in sorted(os.listdir(videos_dir)):
            if os.path.splitext(filename)[1].lower() in video_extensions:
                file_path = os.path.join(videos_dir, filename)
                try:
                    stat_info = os.stat(file_path)
                    result["videos"].append({
                        "filename": filename,
                        "url": f"/media/{set_id}/videos/{filename}",
                        "size_bytes": stat_info.st_size,
                        "modified": stat_info.st_mtime
                    })
                except Exception as e:
                    print(f"[WARN] Could not stat {file_path}: {e}")
    
    
    return result

# Upload hero image for a set
@app.post("/api/sets/{set_id}/media/hero")
async def upload_hero_image(set_id: str, file: UploadFile = File(...)):
    """Upload a hero image for a set.
    
    Accepts: image files (jpg, jpeg, png, gif, webp)
    Saves to: /mnt/legotimelapse/media/{set_id}/hero.{ext}
    Only one hero image per set; replaces existing.
    """
    base_dir = "/mnt/legotimelapse"
    media_dir = os.path.join(base_dir, "media", set_id)
    
    # Validate file type
    allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in allowed_extensions:
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid file type. Allowed: {', '.join(allowed_extensions)}"}
        )
    
    # Create directory if needed
    os.makedirs(media_dir, exist_ok=True)
    
    # Remove any existing hero image
    for ext in allowed_extensions:
        old_hero = os.path.join(media_dir, f"hero{ext}")
        if os.path.exists(old_hero):
            os.remove(old_hero)
    
    # Save new hero image
    hero_path = os.path.join(media_dir, f"hero{file_ext}")
    with open(hero_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    return {
        "filename": f"hero{file_ext}",
        "url": f"/media/{set_id}/hero{file_ext}",
        "size_bytes": os.path.getsize(hero_path)
    }

# Upload photos for a set
@app.post("/api/sets/{set_id}/media/photos")
async def upload_photos(set_id: str, files: List[UploadFile] = File(...)):
    """Upload one or more photos for a set.
    
    Accepts: image files (jpg, jpeg, png, gif, webp)
    Saves to: /mnt/legotimelapse/media/{set_id}/photos/
    """
    base_dir = "/mnt/legotimelapse"
    photos_dir = os.path.join(base_dir, "media", set_id, "photos")
    
    allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
    os.makedirs(photos_dir, exist_ok=True)
    
    uploaded = []
    errors = []
    
    for file in files:
        file_ext = os.path.splitext(file.filename)[1].lower()
        if file_ext not in allowed_extensions:
            errors.append(f"{file.filename}: Invalid file type")
            continue
        
        # Save with original filename (or make unique if exists)
        file_path = os.path.join(photos_dir, file.filename)
        if os.path.exists(file_path):
            # Add timestamp to make unique
            import time
            name, ext = os.path.splitext(file.filename)
            unique_name = f"{name}_{int(time.time())}{ext}"
            file_path = os.path.join(photos_dir, unique_name)
            final_filename = unique_name
        else:
            final_filename = file.filename
        
        try:
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            uploaded.append({
                "filename": final_filename,
                "url": f"/media/{set_id}/photos/{final_filename}",
                "size_bytes": os.path.getsize(file_path)
            })
        except Exception as e:
            errors.append(f"{file.filename}: {str(e)}")
    
    return {"uploaded": uploaded, "errors": errors}

# Upload videos for a set
@app.post("/api/sets/{set_id}/media/videos")
async def upload_videos(set_id: str, files: List[UploadFile] = File(...)):
    """Upload one or more videos for a set (not timelapses).
    
    Accepts: video files (mp4, mov, avi, mkv, webm)
    Saves to: /mnt/legotimelapse/media/{set_id}/videos/
    """
    base_dir = "/mnt/legotimelapse"
    videos_dir = os.path.join(base_dir, "media", set_id, "videos")
    
    allowed_extensions = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}
    os.makedirs(videos_dir, exist_ok=True)
    
    uploaded = []
    errors = []
    
    for file in files:
        file_ext = os.path.splitext(file.filename)[1].lower()
        if file_ext not in allowed_extensions:
            errors.append(f"{file.filename}: Invalid file type")
            continue
        
        # Save with original filename (or make unique if exists)
        file_path = os.path.join(videos_dir, file.filename)
        if os.path.exists(file_path):
            # Add timestamp to make unique
            import time
            name, ext = os.path.splitext(file.filename)
            unique_name = f"{name}_{int(time.time())}{ext}"
            file_path = os.path.join(videos_dir, unique_name)
            final_filename = unique_name
        else:
            final_filename = file.filename
        
        try:
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            uploaded.append({
                "filename": final_filename,
                "url": f"/media/{set_id}/videos/{final_filename}",
                "size_bytes": os.path.getsize(file_path)
            })
        except Exception as e:
            errors.append(f"{file.filename}: {str(e)}")
    
    return {"uploaded": uploaded, "errors": errors}

# Get current page and instruction number as status
@app.get("/api/status")
async def get():
    return {"page": last_page, "document": last_document, "set": last_set, "phase": last_phase}

# Get camera monitor status
@app.get("/api/monitor/status")
async def get_monitor_status():
    return camera_monitor_status

# Update camera monitor status
@app.post("/api/monitor/update")
async def update_monitor_status(request: Request):
    data = await request.json()
    global camera_monitor_status
    
    # Update only the fields that were provided
    for key in data:
        if key in camera_monitor_status:
            camera_monitor_status[key] = data[key]
    
    # Update timestamp automatically
    camera_monitor_status["last_update"] = time.time()
    
    # Broadcast the status update via websockets
    await manager.broadcast(json.dumps({"monitor_status": camera_monitor_status}))
    
    return {"success": True}

@app.post("/api/monitor/capture")
async def set_capture_state(request: Request):
    """Enable or disable active capture from the UI.

    JSON body: {"enabled": true|false}
    Broadcasts updated monitor status via websocket.
    """
    global camera_monitor_status
    try:
        data = await request.json()
        enabled = bool(data.get("enabled"))
        camera_monitor_status["capture_enabled"] = enabled
        camera_monitor_status["last_update"] = time.time()
        await manager.broadcast(json.dumps({"monitor_status": camera_monitor_status}))
        return {"success": True, "capture_enabled": enabled}
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"Invalid request: {e}"})

# Handle the page update request, taking the page number and instruction number from the json body
@app.post("/api/update")
async def update(request: Request):
    data = await request.json()
    # Get client_id from the request if it exists, otherwise set to unknown
    client_id = "unknown"
    if "client_id" in data:
        client_id = data["client_id"]

    # Check to see if page/document is set to check if the update is from a page chage
    # or if the filename is set as an update from the timelapse
    if "instructions" in data:
        global last_page
        global last_document
        global last_set
        global last_phase

        instructiondata = data["instructions"]

        last_page = instructiondata["page"]
        last_document = instructiondata["document"]
        last_set = instructiondata["set"]
        last_phase = instructiondata["phase"]

        # Send update to all connected clients as JSON
        await sendDocumentUpdate(last_page, last_document, client_id)

        return {"page": last_page, "instruction_number": last_document}
    elif "timelapse" in data:
        timelapsedata = data["timelapse"]

        last_timelapse = timelapsedata["filename"]
        set_number = timelapsedata["set_number"]
        phase = timelapsedata["phase"]
        timestamp = timelapsedata["timestamp"]

        # Send update to all connected clients as JSON
        await manager.broadcast(f'{{"timelapse": {{"set_number": "{set_number}", "phase": "{phase}","last_timelapse": "{last_timelapse}", "timestamp": {timestamp}}}}}')

        return {"last_timelapse": last_timelapse}


# List connected cameras with gphoto2
@app.get("/api/cameras")
async def get():
    cameras = []
    gp_cameras = gp.Camera.autodetect()
    for name, addr in gp_cameras:
        cameras.append({"name": name, "address": addr})
    return cameras

# List all images for a set number and phase
@app.get("/api/images/{set_number}/{phase}")
async def get(set_number: str, phase: str):
    images = []
    # Check if the set number and phase directories exist
    if not os.path.exists(f"/mnt/legotimelapse/captures/{set_number}/{phase}"):
        return images
    for image in os.listdir(f"/mnt/legotimelapse/captures/{set_number}/{phase}"):
        image_obj = {
            "filename": image,
            "url": f"/timelapse/{set_number}/{phase}/{image}"
        }
        images.append(image_obj)
    return images

# Start new timelapse encoding via websocket
@app.post("/api/images/{set_number}/{phase}/encode")
async def encode(set_number: str, phase: str, request: Request):
    # Get set name from sets.yml
    with open("sets.yml", "r") as f:
        sets = yaml.safe_load(f)
        for lego_set in sets['sets']:
            if lego_set['id'] == set_number:
                set_name = lego_set['name']
    
    # Get request data for exposure settings
    request_data = await request.json()
    exposure_settings = {}
    
    # Check if exposure settings were provided
    if 'exposure' in request_data:
        exposure_settings = request_data['exposure']
        # Send message to websocket to start encoding timelapse with exposure settings
        await manager.broadcast(json.dumps({
            "encode": {
                "set_number": set_number,
                "set_name": set_name,
                "phase": phase,
                "exposure": exposure_settings
            }
        }))
    else:
        # Send message to websocket to start encoding timelapse without exposure settings
        await manager.broadcast(f'{{"encode": {{"set_number": "{set_number}", "set_name": "{set_name}", "phase": "{phase}"}}}}')
    
    return {"message": "Encoding timelapse"}

# API Endpoint to move to the next page
@app.post("/api/next")
async def next_page():
    global last_page
    # TODO: Check if the page is already at the last page, if so, don't go beyond the last page
    last_page += 1
    await sendDocumentUpdate(last_page, last_document, "api")
    return {"page": last_page, "document": last_document}

# API Endpoint to move to the previous page
@app.post("/api/previous")
async def previous_page():
    global last_page
    # Check if the page is already at 1, if so, don't go below 1
    if last_page == 1:
        return {"page": last_page, "document": last_document}
    last_page -= 1
    await sendDocumentUpdate(last_page, last_document, "api")
    return {"page": last_page, "document": last_document}

# API Endpoint to move to the next instruction (document)
@app.post("/api/instruction/next")
async def next_instruction():
    global last_document, last_page, last_set
    try:
        # Load sets.yml and find current set
        with open("sets.yml", "r") as f:
            sets_data = yaml.safe_load(f)
        current_set = None
        for s in sets_data.get('sets', []):
            if s.get('id') == last_set:
                current_set = s
                break
        if not current_set:
            return JSONResponse(status_code=404, content={"error": f"Set {last_set} not found"})
        instructions = current_set.get('instructions', [])
        if not instructions:
            return JSONResponse(status_code=404, content={"error": f"No instructions for set {last_set}"})
        # Parse current instruction number from last_document path
        # Format expected: /instructions/<set_id>/<instruction_number>
        parts = last_document.strip('/').split('/')
        current_instruction_number = parts[-1] if len(parts) >= 3 else None
        try:
            idx = instructions.index(current_instruction_number) if current_instruction_number in instructions else -1
        except ValueError:
            idx = -1
        # Advance index (wrap at end)
        next_idx = (idx + 1) % len(instructions)
        next_instruction_number = instructions[next_idx]
        
        # Only update if actually changing to a different instruction
        if next_instruction_number == current_instruction_number:
            # Single instruction or wrapped back to same one - no change
            return {"page": last_page, "document": last_document, "instruction": current_instruction_number, "changed": False}
        
        last_document = f"/instructions/{last_set}/{next_instruction_number}"
        last_page = 1  # reset page counter on instruction change
        await sendDocumentUpdate(last_page, last_document, "api")
        return {"page": last_page, "document": last_document, "instruction": next_instruction_number, "changed": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Failed to move to next instruction: {e}"})

# API Endpoint to move to the previous instruction (document)
@app.post("/api/instruction/previous")
async def previous_instruction():
    global last_document, last_page, last_set
    try:
        with open("sets.yml", "r") as f:
            sets_data = yaml.safe_load(f)
        current_set = None
        for s in sets_data.get('sets', []):
            if s.get('id') == last_set:
                current_set = s
                break
        if not current_set:
            return JSONResponse(status_code=404, content={"error": f"Set {last_set} not found"})
        instructions = current_set.get('instructions', [])
        if not instructions:
            return JSONResponse(status_code=404, content={"error": f"No instructions for set {last_set}"})
        parts = last_document.strip('/').split('/')
        current_instruction_number = parts[-1] if len(parts) >= 3 else None
        try:
            idx = instructions.index(current_instruction_number) if current_instruction_number in instructions else 0
        except ValueError:
            idx = 0
        prev_idx = (idx - 1) % len(instructions)
        prev_instruction_number = instructions[prev_idx]
        
        # Only update if actually changing to a different instruction
        if prev_instruction_number == current_instruction_number:
            # Single instruction or wrapped back to same one - no change
            return {"page": last_page, "document": last_document, "instruction": current_instruction_number, "changed": False}
        
        last_document = f"/instructions/{last_set}/{prev_instruction_number}"
        last_page = 1
        await sendDocumentUpdate(last_page, last_document, "api")
        return {"page": last_page, "document": last_document, "instruction": prev_instruction_number, "changed": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Failed to move to previous instruction: {e}"})

# API Endpoint to activate a set (changes current set and resets document/page)
@app.post("/api/set/{set_id}/activate")
async def activate_set(set_id: str):
    global last_set, last_document, last_page
    try:
        with open("sets.yml", "r") as f:
            sets_data = yaml.safe_load(f)
        target = None
        for s in sets_data.get('sets', []):
            if s.get('id') == set_id:
                target = s
                break
        if not target:
            return JSONResponse(status_code=404, content={"error": f"Set {set_id} not found"})
        instructions = target.get('instructions', [])
        last_set = set_id
        if instructions:
            first_instruction = instructions[0]
            last_document = f"/instructions/{set_id}/{first_instruction}"
        else:
            # No instructions, keep last_document pointing to previous or placeholder
            last_document = f"/instructions/{set_id}/NONE"
        last_page = 1
        await sendDocumentUpdate(last_page, last_document, "api")
        return {
            "set": last_set,
            "document": last_document,
            "page": last_page,
            "instructions_count": len(instructions)
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Failed to activate set: {e}"})

@app.post("/api/capture-test-image")
async def capture_test_image(request: Request):
    """Capture a test image using unified capture manager (methods: auto, picamera2, opencv, rpicam, raspistill)."""
    try:
        params = {}
        if request.headers.get('content-type','').startswith('application/json'):
            params = await request.json()
    except Exception:
        params = {}
    method = params.get('method', 'auto')
    device_index = int(params.get('device_index', 0))
    width = params.get('width')
    height = params.get('height')
    warmup_frames = int(params.get('warmup_frames', 5))

    try:
        result = captureManager.capture(method=method, device_index=device_index, width=width, height=height, warmup_frames=warmup_frames)
        return {
            "image_url": "/api/test-image",
            "method_requested": result["method_requested"],
            "method_used": result["method_used"],
            "attempts": result["attempts"]
        }
    except CameraCaptureError as ce:
        return JSONResponse(status_code=500, content={
            "error": str(ce),
            "method_requested": method,
            "attempts": []
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "error": f"Unexpected error: {e}",
            "method_requested": method,
            "attempts": []
        })

@app.get("/api/test-image")
async def get_test_image():
    test_image_path = "/tmp/pi_test_image.jpg"
    if not os.path.exists(test_image_path):
        return JSONResponse(status_code=404, content={"error": "No test image found"})
    return FileResponse(test_image_path, media_type="image/jpeg")

@app.get("/api/video-stream")
async def video_stream():
    def gen_frames():
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            raise RuntimeError("Could not open video device")
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    continue
                ret, jpeg = cv2.imencode('.jpg', frame)
                if not ret:
                    continue
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
        finally:
            cap.release()
    return StreamingResponse(gen_frames(), media_type='multipart/x-mixed-replace; boundary=frame')

@app.get("/video-stream", include_in_schema=False)
async def get():
    return FileResponse("templates/video_stream.html")

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: int):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.send_personal_message(f'{{"message": "You sent: {data}"}}', websocket)
            await manager.broadcast(f'{{"message": "Client #{client_id} says: {data}"}}')
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await manager.broadcast(f'{{"meta_control":{{"status":"disconnect","detail":"Client #{client_id} has disconnected","client_id":{client_id}}}}}')

