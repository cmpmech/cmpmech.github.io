#!/usr/bin/env bash
# Encode a frame folder or an existing video into a web-ready H.264 mp4:
# no audio, even dimensions, yuv420p/bt709, faststart (plays while downloading).
#
# Usage:
#   web_video.sh <frames_dir|input.mp4> <output.mp4> [options]
# Options (environment variables):
#   PATTERN=frame_%d.jpg  frame file pattern (frame folders only)
#   FPS=30                frame rate (frame folders only)
#   CRF=28                quality, lower is better (18-23 near lossless, ~28 for web)
#   WIDTH=                scale to this width (keeps aspect ratio), empty = keep
#   POSTER=1              also write <output>-poster.jpg from the last frame
#
# Examples:
#   web_video.sh results/frames/learning_image assets/learning_image.mp4
#   WIDTH=640 CRF=26 web_video.sh firstlayer_fast.mp4 assets/firstlayer.mp4
set -euo pipefail

input=${1:?input frames dir or video}
output=${2:?output mp4}
PATTERN=${PATTERN:-frame_%d.jpg}
FPS=${FPS:-30}
CRF=${CRF:-28}
WIDTH=${WIDTH:-}
POSTER=${POSTER:-1}

if [[ -d $input ]]; then
  src=(-framerate "$FPS" -i "$input/$PATTERN")
else
  src=(-i "$input")
fi

if [[ -n $WIDTH ]]; then
  vf="scale=${WIDTH}:-2"
else
  vf="crop=trunc(iw/2)*2:trunc(ih/2)*2"
fi

mkdir -p "$(dirname "$output")"
ffmpeg -y -loglevel error "${src[@]}" -an -vf "$vf" \
  -c:v libx264 -preset slow -crf "$CRF" -pix_fmt yuv420p \
  -colorspace bt709 -color_range tv -movflags +faststart "$output"

if [[ $POSTER == 1 ]]; then
  ffmpeg -y -loglevel error -sseof -0.1 -i "$output" -frames:v 1 -q:v 3 \
    "${output%.mp4}-poster.jpg"
fi

echo "saved $output ($(du -h "$output" | cut -f1))"
