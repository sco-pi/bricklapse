from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse
from typing import List
import yaml
import shutil
import os
import gphoto2 as gp

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

instructions_dir = "/mnt/legotimelapse/instructions"
last_page = 1
last_document = "/instructions/42158/6501852" # Defaults to the Mars Rover set, need to find a better way to default

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

# Default UI Linking to Control, Viewer, and WS Log UIs
@app.get("/")
async def get():
    return FileResponse("templates/index.html")

@app.get("/control")
async def get():
    return FileResponse("templates/control.html")

# Viewer UI
@app.get("/viewer")
async def get():
    return FileResponse("templates/viewer.html")

# Sets UI
@app.get("/sets")
async def get():
    return FileResponse("templates/sets.html")

# Temp Chat UI to test websocket connection
@app.get("/wslog")
async def get():
    return FileResponse("templates/wslog.html")

# Get Image UI
@app.get("/images")
async def get():
    return FileResponse("templates/imageview.html")

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

# Get current page and instruction number as status
@app.get("/api/status")
async def get():
    return {"page": last_page, "document": last_document}

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

        instructiondata = data["instructions"]

        last_page = instructiondata["page"]
        last_document = instructiondata["document"]

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
async def encode(set_number: str, phase: str):
    # Get set name from sets.yml
    with open("sets.yml", "r") as f:
        sets = yaml.safe_load(f)
        for lego_set in sets['sets']:
            if lego_set['id'] == set_number:
                set_name = lego_set['name']
    # Send message to websocket to start encoding timelapse
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

