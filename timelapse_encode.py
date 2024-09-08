# Use FFMPEG to encode a timelapse video from the collected images for a given set

import ffmpeg

BASE_DIR = '/mnt/legotimelapse/'
SET_NUMBER = '31131'
SET_NAME = 'Tea Shop'
PHASE = 'build'
OUTPUT_RESOLUTION = '1080x1350' # 4:5 aspect ratio for Instagram
TITLE_TIME = 5

# Convert Phase to sensible name, defaulting to title case if not recognized
phase_text = PHASE.title()
if PHASE == 'build':
    phase_text = 'Build'
elif PHASE == 'dissasemble':
    phase_text = 'Disassembly'
elif PHASE == 'sort':
    phase_text = 'Sorting'
    

# Calculate decimal ratio from output resolution
output_res_x = int(OUTPUT_RESOLUTION.split('x')[0])
output_res_y = int(OUTPUT_RESOLUTION.split('x')[1])
output_ratio = output_res_x / output_res_y

# Get dimensions of first frame in capture to help set crop filter
probe = ffmpeg.probe(f'{BASE_DIR}/captures/{SET_NUMBER}/{PHASE}/frame00001.jpg')
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

run_ffmpeg = True
if run_ffmpeg:
    stream = ffmpeg.input( f'{BASE_DIR}/captures/{SET_NUMBER}/{PHASE}/frame%05d.jpg', framerate=60, pattern_type='sequence', start_number=1)

    # Crop video to 3200x4000 starting at 1600x0
    #stream = ffmpeg.filter(stream, 'crop', 3200, 4000, 1600, 0)
    stream = ffmpeg.filter(stream, 'crop', crop_width, crop_height, crop_x, crop_y)

    # Overlay the set number and name on the top left of the video for the first TITLE_TIME seconds
    set_and_phase = f'#{SET_NUMBER} - {phase_text}'
    stream = ffmpeg.drawtext(stream, text=set_and_phase, x=50, y=50, fontsize=180, fontcolor='white', box=1, boxcolor='black@0.5', enable=f'between(t,0,{TITLE_TIME})')
    stream = ffmpeg.drawtext(stream, text=SET_NAME, x=50, y=240, fontsize=180, fontcolor='white', box=1, boxcolor='black@0.5', enable=f'between(t,0,{TITLE_TIME})')

    # Overlay logo on top right of video
    logo = ffmpeg.input('BorrowLapse.png')
    stream = ffmpeg.overlay(stream, logo, x=crop_width-700, y=0)

    stream = ffmpeg.output(stream, f'{BASE_DIR}/{SET_NUMBER} - {SET_NAME} - {PHASE}-temp.mp4', s=OUTPUT_RESOLUTION, c='libx264', crf=17, pix_fmt='yuv420p')

    ffmpeg.run(stream)
