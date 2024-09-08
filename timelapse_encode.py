# Implement the following ffmpeg command in Python:
# ffmpeg \
#  -framerate 60 \
#  -pattern_type sequence \
#  -start_number 00001 \
#  -i "/mnt/legotimelapse/captures/31131/dissasemble/frame%05d.jpg" \
#  -s:v 1080x1350 \
#  -c:v libx264  \
#  -vf "crop=3200:4000:1600:0" \
#  -crf 17 \
#  -pix_fmt yuv420p \
#  "/mnt/legotimelapse/31131 - Tea Shop - Dissasenbly.mp4"

import ffmpeg

BASE_DIR = '/mnt/legotimelapse/'
SET_NUMBER = '31131'
SET_NAME = 'Tea Shop'
PHASE = 'dissasemble'
OUTPUT_RESOLUTION = '1080x1350'
CROP = '3200:4000:1600:0'

stream = ffmpeg.input( f'{BASE_DIR}/captures/{SET_NUMBER}/{PHASE}/frame%05d.jpg', framerate=60, pattern_type='sequence', start_number=1)
# Overlay logo on top of video
# logo = ffmpeg.input('BorrowLapse.png')
# stream = ffmpeg.overlay(stream, logo, x=0, y=0)

stream = ffmpeg.output(stream, f'{BASE_DIR}/{SET_NUMBER} - {SET_NAME} - {PHASE}.mp4', s=OUTPUT_RESOLUTION, c='libx264', vf=f'crop={CROP}', crf=17, pix_fmt='yuv420p')

ffmpeg.run(stream)
