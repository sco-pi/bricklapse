# Use FFMPEG to encode a timelapse video from the collected images for a given set

import ffmpeg
import websocket
import _thread
import time
import rel
import json

API_HOST = '192.168.1.60:8000'
BASE_DIR = '/mnt/legotimelapse'
OUTPUT_RESOLUTION = '1080x1350' # 4:5 aspect ratio for Instagram

# Convert Phase to sensible name, defaulting to title case if not recognized
def phaseToText(phase):
    phase_text = phase.title()
    if phase == 'build':
        phase_text = 'Build'
    elif phase == 'build1':
        phase_text = 'Build Alternate 1'
    elif phase == 'build2':
        phase_text = 'Build Alternate 2'
    elif phase == 'build3':
        phase_text = 'Build Alternate 3'
    elif phase == 'install_lights':
        phase_text = 'Install Lights'
    elif phase == 'disassemble':
        phase_text = 'Disassembly'
    elif phase == 'sort':
        phase_text = 'Sorting'
    return phase_text
    
def getCropFilter(OutputResolutionX, OutputResolutionY, firstFramePath):
    # Calculate decimal ratio from output resolution
    output_ratio = int(OutputResolutionX) / int(OutputResolutionY)

    # Get dimensions of first frame in capture to help set crop filter
    probe = ffmpeg.probe(firstFramePath)
    src_width = probe['streams'][0]['width']
    src_height = probe['streams'][0]['height']

    # Find the largest crop that fits within the source dimensions and matches the output ratio from the center of the source
    crop_width = src_height * output_ratio
    crop_height = src_height
    crop_x = (src_width - crop_width) / 2
    crop_y = 0

    # If the crop width is larger than the source width, adjust the crop to fit within the source width
    if crop_width > src_width:
        crop_width = src_width
        crop_height = src_width / output_ratio
        crop_x = 0
        crop_y = (src_height - crop_height) / 2

    print(f"Source width: {src_width}, Source height: {src_height}")
    print(f"Crop width: {crop_width}, Crop height: {crop_height}")
    print(f"Crop filter: {crop_width}:{crop_height}:{crop_x}:{crop_y}")
    print(f"Output ratio: {output_ratio}")

    return crop_width, crop_height, crop_x, crop_y

def createTimelaspe(BasePath, FilePattern, FirstFile, OutputDir, OutputResX, OutputResY, SetNumber, SetName, Phase, TitleTime=5, logoPath='BorrowLapse.png', ExposureSettings=None):
    stream = ffmpeg.input( f'{BasePath}/{FilePattern}', framerate=60, pattern_type='sequence', start_number=0)

    # Crop video to 3200x4000 starting at 1600x0
    #stream = ffmpeg.filter(stream, 'crop', 3200, 4000, 1600, 0)
    crop_width, crop_height, crop_x, crop_y = getCropFilter(OutputResX, OutputResY, f'{BasePath}/{FirstFile}')
    stream = ffmpeg.filter(stream, 'crop', crop_width, crop_height, crop_x, crop_y)
    
    # Apply exposure adjustments if provided
    if ExposureSettings:
        # Apply brightness and contrast adjustments if they exist and are not zero
        if 'brightness' in ExposureSettings and ExposureSettings['brightness'] != 0:
            # FFMPEG eq filter uses values from -1 to 1, so normalize from our -100 to 100 range
            brightness_value = float(ExposureSettings['brightness']) / 100
            stream = ffmpeg.filter(stream, 'eq', brightness=brightness_value)
            print(f"Applied brightness adjustment: {brightness_value}")
            
        if 'contrast' in ExposureSettings and ExposureSettings['contrast'] != 0:
            # FFMPEG eq filter uses values starting at 1 (1 is normal, 2 is more contrast)
            # Convert our -100 to 100 range to 0.5 to 1.5 range
            contrast_value = 1 + (float(ExposureSettings['contrast']) / 100)
            stream = ffmpeg.filter(stream, 'eq', contrast=contrast_value)
            print(f"Applied contrast adjustment: {contrast_value}")

    # Overlay the set number and name on the top left of the video for the first TitleTime seconds
    SetAndPhase = f'#{SetNumber} - {phaseToText(Phase)}'
    stream = ffmpeg.drawtext(stream, text=SetAndPhase, x=50, y=50,  fontsize=180, fontcolor='white', box=1, boxcolor='black@0.5', enable=f'between(t,0,{TitleTime})')
    stream = ffmpeg.drawtext(stream, text=SetName,     x=50, y=240, fontsize=180, fontcolor='white', box=1, boxcolor='black@0.5', enable=f'between(t,0,{TitleTime})')

    # Overlay logo on top right of video
    logo = ffmpeg.input(logoPath)
    stream = ffmpeg.overlay(stream, logo, x=crop_width-700, y=0)

    # TODO: Remove Temp from the filename
    stream = ffmpeg.output(stream, f'{OutputDir}/{SetNumber} - {SetName} - {Phase}-temp.mp4', s=f'{OutputResX}x{OutputResY}', c='libx264', crf=17, pix_fmt='yuv420p')

    ffmpeg.run(stream, overwrite_output=True)

# Subscribe to websocker server to get requests to encode timelapse videos and start the createTimelapse function with the parameters from the request
# Websockets on ws://{API_HOST}/ws/{client_id}
def on_message(ws, message):
    print(message)
    data = json.loads(message)
    # Check if message has an encode key
    if data["encode"]:
        encode_data = data["encode"]
        # Check if the encode data has the required keys
        if "set_number" in encode_data and "set_name" in encode_data and "phase" in encode_data:
            # Check for exposure settings
            exposure_settings = None
            if "exposure" in encode_data:
                exposure_settings = encode_data["exposure"]
                print(f"Received exposure settings: {exposure_settings}")
                
            createTimelaspe(
                BasePath=f'{BASE_DIR}/captures/{encode_data["set_number"]}/{encode_data["phase"]}',
                FilePattern="frame%05d.jpg",
                FirstFile="frame00001.jpg",
                OutputDir=BASE_DIR,
                OutputResX=OUTPUT_RESOLUTION.split('x')[0],
                OutputResY=OUTPUT_RESOLUTION.split('x')[1],
                SetNumber=encode_data["set_number"],
                SetName=encode_data["set_name"],
                Phase=encode_data["phase"],
                ExposureSettings=exposure_settings
            )
        else:
            print("Missing required keys in encode data")
    else:
        print("Missing encode key in message")

def on_error(ws, error):
    print(error)

def on_close(ws, close_status_code, close_msg):
    print("### closed ###")

def on_open(ws):
    print("Opened connection")

if __name__ == "__main__":
    #websocket.enableTrace(True)
    ws = websocket.WebSocketApp(f'ws://{API_HOST}/ws/1321',
                              on_open=on_open,
                              on_message=on_message,
                              on_error=on_error,
                              on_close=on_close)

    ws.run_forever(dispatcher=rel, reconnect=5)  # Set dispatcher to automatic reconnection, 5 second reconnect delay if connection closed unexpectedly
    rel.signal(2, rel.abort)  # Keyboard Interrupt
    rel.dispatch()