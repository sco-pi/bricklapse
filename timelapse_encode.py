# Use FFMPEG to encode a timelapse video from the collected images for a given set

import ffmpeg
import websocket
import _thread
import time
import rel
import json

API_HOST = '127.0.0.1:8000'
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

def calculateOverlayDimensions(output_width, output_height,
                               font_pct=0.055,            # 5.5% of height (previously 7%)
                               margin_pct=0.025,          # 2.5% margins
                               line_gap_font_pct=0.18,    # gap below first line = 18% of font size
                               logo_width_pct=0.15        # logo width ~15% of output width
                               ):
    """Calculate overlay dimensions relative to FINAL scaled output resolution.

    font_pct: percentage of output HEIGHT used for font size.
    margin_pct: uniform horizontal & vertical margin as % of width/height.
    line_gap_font_pct: additional gap below first line relative to font size (not absolute height).
    logo_width_pct: logo width relative to output WIDTH; height auto-preserved with -1.
    """
    font_size = max(12, int(output_height * font_pct))
    margin_x = int(output_width * margin_pct)
    margin_y = int(output_height * margin_pct)
    second_line_y = margin_y + font_size + int(font_size * line_gap_font_pct)
    logo_target_width = max(32, int(output_width * logo_width_pct))
    return {
        'text_margin_x': margin_x,
        'text_margin_y': margin_y,
        'font_size': font_size,
        'second_line_y': second_line_y,
        'logo_target_width': logo_target_width,
        'logo_margin': margin_x,
    }
    
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

def createTimelaspe(BasePath, FilePattern, FirstFile, OutputDir, OutputResX, OutputResY,
                    SetNumber, SetName, Phase, TitleTime=5, logoPath='BorrowLapse.png',
                    ExposureSettings=None,
                    font_pct=0.055, margin_pct=0.025, line_gap_font_pct=0.18, logo_width_pct=0.15):
    stream = ffmpeg.input(f'{BasePath}/{FilePattern}', framerate=60, pattern_type='sequence', start_number=0)

    # Crop video to 3200x4000 starting at 1600x0
    #stream = ffmpeg.filter(stream, 'crop', 3200, 4000, 1600, 0)
    crop_width, crop_height, crop_x, crop_y = getCropFilter(OutputResX, OutputResY, f'{BasePath}/{FirstFile}')
    stream = ffmpeg.filter(stream, 'crop', crop_width, crop_height, crop_x, crop_y)

    # SCALE to final output resolution BEFORE overlays so positioning is correct across differing source sizes
    output_width = int(OutputResX)
    output_height = int(OutputResY)
    stream = ffmpeg.filter(stream, 'scale', output_width, output_height)
    print(f"Scaled cropped frames to {output_width}x{output_height} before applying overlays")

    # Calculate overlay dimensions relative to FINAL scaled size
    overlay_dims = calculateOverlayDimensions(output_width, output_height,
                                              font_pct=font_pct,
                                              margin_pct=margin_pct,
                                              line_gap_font_pct=line_gap_font_pct,
                                              logo_width_pct=logo_width_pct)

    print(f"Overlay dimensions: margin=({overlay_dims['text_margin_x']},{overlay_dims['text_margin_y']}) font={overlay_dims['font_size']} second_line_y={overlay_dims['second_line_y']} logo_w={overlay_dims['logo_target_width']}")
    
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
    stream = ffmpeg.drawtext(stream, text=SetAndPhase,
                             x=overlay_dims['text_margin_x'], y=overlay_dims['text_margin_y'],
                             fontsize=overlay_dims['font_size'], fontcolor='white', box=1,
                             boxcolor='black@0.5', enable=f'between(t,0,{TitleTime})')
    stream = ffmpeg.drawtext(stream, text=SetName,
                             x=overlay_dims['text_margin_x'], y=overlay_dims['second_line_y'],
                             fontsize=overlay_dims['font_size'], fontcolor='white', box=1,
                             boxcolor='black@0.5', enable=f'between(t,0,{TitleTime})')

    # Overlay logo on top right of video - scale logo relative to output width
    logo = ffmpeg.input(logoPath)
    # Scale logo to target width, keep aspect: height -1 lets ffmpeg auto-calc
    logo = ffmpeg.filter(logo, 'scale', overlay_dims['logo_target_width'], -1)
    logo_x_pos = output_width - overlay_dims['logo_target_width'] - overlay_dims['logo_margin']
    stream = ffmpeg.overlay(stream, logo, x=logo_x_pos, y=overlay_dims['text_margin_y'])
    print(f"Logo positioned at x={logo_x_pos} y={overlay_dims['text_margin_y']}")

    # TODO: Remove Temp from the filename
    # No -s parameter needed; already scaled
    stream = ffmpeg.output(stream, f'{OutputDir}/{SetNumber} - {SetName} - {Phase}-temp.mp4', c='libx264', crf=17, pix_fmt='yuv420p')

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