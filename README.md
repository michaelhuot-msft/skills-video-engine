# Explainer Video Engine

Public OCI image containing the generation toolchain used by the
[explainer-video skill](https://github.com/mhuot/explainer-video-skill):

- HyperFrames for deterministic HTML/CSS/JavaScript video rendering
- Kokoro-82M for local narration
- FFmpeg and FFprobe for encoding and media QA
- Python 3.12, Node.js 22, Chromium, and chrome-headless-shell

After the image is pulled, generation can run without network access. Project
files remain on the host and are mounted into `/project`.

## Status

The initial image is Linux AMD64 only. ARM64 support will be added after the
complete Kokoro and HyperFrames pipeline is validated on that architecture.

## Pull

```bash
docker pull ghcr.io/michaelhuot-msft/explainer-video-engine:latest
```

For repeatable production, use a version tag or image digest instead of
`latest`.

## Use

Mount an explainer-video project and invoke the underlying tools directly:

```bash
docker run --rm \
  --user "$(id -u):$(id -g)" \
  -v "$PWD:/project" \
  ghcr.io/michaelhuot-msft/explainer-video-engine:latest \
  python tools/tts_generate.py
```

```bash
docker run --rm \
  --user "$(id -u):$(id -g)" \
  -v "$PWD:/project" \
  ghcr.io/michaelhuot-msft/explainer-video-engine:latest \
  hyperframes render video --output production/renders/master.mp4
```

```bash
docker run --rm \
  --user "$(id -u):$(id -g)" \
  -v "$PWD:/project" \
  ghcr.io/michaelhuot-msft/explainer-video-engine:latest \
  ffprobe -v error -show_format -show_streams \
  production/renders/master.mp4
```

On SELinux hosts, append `:Z` to the volume mount. The `--user` option keeps
generated files owned by the current host user.

## Build locally

```bash
docker build --platform linux/amd64 \
  -t explainer-video-engine:local .
bash scripts/smoke_test.sh explainer-video-engine:local
```

The build downloads and caches the pinned Kokoro model revision. It also
includes the corresponding Debian source packages for FFmpeg and x264 under
`/usr/src/third-party`.

## Releases

Git tags matching `v*` publish these GHCR tags:

- Full semantic version, such as `0.1.0`
- Major/minor version, such as `0.1`
- Git SHA
- `latest`

Published images include an SBOM and build-provenance attestations.

## License

Project source is MIT licensed. Container components retain their own licenses;
see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
