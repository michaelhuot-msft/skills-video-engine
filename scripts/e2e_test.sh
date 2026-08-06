#!/usr/bin/env bash
set -euo pipefail

image="${1:-skills-video-engine:test}"
test_uid="${ENGINE_E2E_UID:-12345}"
test_gid="${ENGINE_E2E_GID:-12345}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${script_dir}/.." && pwd)"
fixture_dir="${repository_root}/tests/fixtures/minimal-project"
project_dir="$(mktemp -d)"

cleanup() {
  rm -rf "${project_dir}"
}
trap cleanup EXIT

cp -R "${fixture_dir}/." "${project_dir}/"
mkdir -p \
  "${project_dir}/video/assets/audio" \
  "${project_dir}/production/renders" \
  "${project_dir}/production/snapshots"

curl --fail --location --retry 3 --max-time 60 \
  https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js \
  --output "${project_dir}/video/assets/gsap.min.js"
test -s "${project_dir}/video/assets/gsap.min.js"
chmod -R a+rwX "${project_dir}"

run_in() {
  local container_workdir="$1"
  shift
  docker run --rm \
    --init \
    --shm-size=1g \
    --network none \
    --user "${test_uid}:${test_gid}" \
    --volume "${project_dir}:/project" \
    --workdir "${container_workdir}" \
    "${image}" \
    "$@"
}

run_in /project sh -c \
  "test \"\$(id -u)\" = \"${test_uid}\" &&
   test \"\$(id -g)\" = \"${test_gid}\" &&
   mkdir -p \"\${XDG_CACHE_HOME}/engine-e2e\" \"\${HOME}/.config/chromium-e2e\""

run_in /project python generate_narration.py
test -s "${project_dir}/video/assets/audio/narration.wav"
test -s "${project_dir}/durations.json"
test -s "${project_dir}/video/index.html"

run_in /project/video hyperframes lint
run_in /project/video hyperframes check
run_in /project/video hyperframes snapshot \
  --at 1 \
  --no-end \
  --describe false \
  --output ../production/snapshots
run_in /project/video hyperframes render \
  --output ../production/renders/fixture.mp4

snapshot_path="$(find "${project_dir}/production/snapshots" -type f -name '*.png' -print -quit)"
test -n "${snapshot_path}"
test -s "${project_dir}/production/renders/fixture.mp4"

run_in /project ffprobe \
  -v error \
  -show_entries format=duration \
  -show_entries stream=codec_type,codec_name,width,height \
  -of json \
  production/renders/fixture.mp4 >"${project_dir}/ffprobe.json"

python3 - "${project_dir}/durations.json" "${project_dir}/ffprobe.json" <<'PY'
import json
import sys
from pathlib import Path

timing = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
probe = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))

duration = float(probe["format"]["duration"])
expected = float(timing["total_seconds"])
if abs(duration - expected) > 0.25:
    raise SystemExit(f"duration {duration:.3f}s differs from expected {expected:.3f}s")

video_streams = [
    stream for stream in probe["streams"] if stream.get("codec_type") == "video"
]
audio_streams = [
    stream for stream in probe["streams"] if stream.get("codec_type") == "audio"
]
if not video_streams:
    raise SystemExit("render has no video stream")
if video_streams[0].get("codec_name") != "h264":
    raise SystemExit(f"unexpected video codec: {video_streams[0].get('codec_name')}")
if (video_streams[0].get("width"), video_streams[0].get("height")) != (640, 360):
    raise SystemExit("render dimensions do not match the fixture")
if not audio_streams:
    raise SystemExit("render has no audio stream")
PY

if [[ "$(uname -s)" == "Linux" ]]; then
  while IFS= read -r output_path; do
    owner="$(stat -c '%u:%g' "${output_path}")"
    if [[ "${owner}" != "${test_uid}:${test_gid}" ]]; then
      echo "unexpected output owner ${owner}: ${output_path}" >&2
      exit 1
    fi
  done < <(
    find \
      "${project_dir}/video/assets/audio" \
      "${project_dir}/production" \
      -type f -print
    printf '%s\n' \
      "${project_dir}/durations.json" \
      "${project_dir}/video/index.html"
  )
fi

echo "mounted-project e2e: all checks passed"
