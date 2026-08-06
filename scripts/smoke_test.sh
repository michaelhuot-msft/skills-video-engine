#!/usr/bin/env bash
set -euo pipefail

image="${1:-skills-video-engine:test}"

docker run --rm "${image}" hyperframes --version
docker run --rm "${image}" python --version
docker run --rm "${image}" ffmpeg -hide_banner -version
docker run --rm "${image}" ffprobe -hide_banner -version
docker run --rm "${image}" chrome-headless-shell --version
docker run --rm "${image}" ffmpeg -hide_banner -encoders |
  grep libx264 >/dev/null
docker run --rm --network none "${image}" python -c \
  "from kokoro import KPipeline; KPipeline(lang_code='a', repo_id='hexgrad/Kokoro-82M'); print('Kokoro model ready')"
docker run --rm "${image}" sh -c \
  'test -n "$(find /usr/src/third-party -maxdepth 1 -type d -name "ffmpeg-*")"'
docker run --rm "${image}" sh -c \
  'test -n "$(find /usr/src/third-party -maxdepth 1 -type d -name "x264-*")"'
