# Copilot instructions for mhuot/skills-video-engine

This file summarizes the repository's build/test/lint commands, the high-level architecture, and repository-specific conventions that Copilot sessions should follow.

---

## Build, test, and lint commands

Primary intent: produce and validate the OCI image and bundled tooling.

- Build image (local):
  - docker build -t skills-video-engine:local .

- Run the repository smoke test (full quick validation):
  - bash scripts/smoke_test.sh skills-video-engine:local

- Run individual smoke-test checks (useful for focused validation):
  - docker run --rm skills-video-engine:local hyperframes --version
  - docker run --rm skills-video-engine:local python --version
  - docker run --rm skills-video-engine:local ffmpeg -hide_banner -version
  - docker run --rm skills-video-engine:local ffprobe -hide_banner -version
  - docker run --rm skills-video-engine:local chrome-headless-shell --version
  - docker run --rm skills-video-engine:local python -c "from kokoro import KPipeline; KPipeline(lang_code='a', repo_id='hexgrad/Kokoro-82M'); print('Kokoro model ready')"
  - Verify third-party sources exist in the image:
    - docker run --rm skills-video-engine:local sh -c 'test -n "$(find /usr/src/third-party -maxdepth 1 -type d -name "ffmpeg-*")"'
    - docker run --rm skills-video-engine:local sh -c 'test -n "$(find /usr/src/third-party -maxdepth 1 -type d -name "x264-*")"'

- CI checks used in GitHub Actions:
  - shellcheck scripts/*.sh
  - python -m unittest discover -s scripts -p "test_*.py"

Notes:
- CI runs a matrix build for linux/amd64 and linux/arm64 and executes the smoke test inside each produced image.
- Published images include SBOM and build-provenance metadata.

---

## High-level architecture (big picture)

- Purpose: produce a self-contained OCI image (ghcr.io/mhuot/skills-video-engine) that bundles tools required to generate video "skills": HyperFrames (Node), Kokoro (Python TTS), FFmpeg, Chromium/headless shell, and related media tooling.

- Build stages:
  1. Uses an `uv` helper image to install and manage Python runtimes and venvs.
  2. Uses `node:22-bookworm-slim` as the main base image and installs system packages (chromium, ffmpeg, fonts, etc.) via apt.
  3. Installs HyperFrames globally via npm and configures a headless-chrome binary (puppeteer or playwright flow depending on arch).
  4. Installs Python 3.12 into a venv and uses `huggingface_hub.snapshot_download` to pin and cache the Kokoro model revision. Debian source packages for ffmpeg and x264 are saved under `/usr/src/third-party` for provenance.

- Runtime assumptions:
  - Host project files are mounted at `/project` and tools are invoked from there (WORKDIR /project).
  - Container can run fully offline after the model + artifacts are baked into the image (HF_HUB_OFFLINE=1 at runtime).
  - CMD defaults to `hyperframes --help`; typical usage mounts the host project and runs hyperframes, python TTS scripts, or ffprobe inside the container.

- Multi-arch & release:
  - Buildx is used to build and publish multi-architecture images (amd64 and arm64) with cache-from/cache-to and multi-tagging.
  - Release tags created from Git tags matching `v*` produce multiple tags: semver, major.minor, sha, and `latest`.

---

## Key repository conventions and important details

- Kokoro model and reproducibility:
  - The Kokoro model revision is pinned via the `KOKORO_MODEL_REVISION` build ARG in the Dockerfile. Changes to TTS or model revision must update the ARG and re-run the build/validation.
  - The Dockerfile asserts the downloaded Kokoro snapshot matches the pinned revision; keep this validation when editing build logic.

- Third-party source packaging:
  - Debian source packages for ffmpeg and x264 are downloaded at build time and stored under `/usr/src/third-party`. Smoke tests expect directories named like `ffmpeg-*` and `x264-*` to exist.

- Headless Chromium selection:
  - For amd64 the build uses `@puppeteer/browsers` to install chrome-headless-shell; for arm64 it installs playwright's chromium-headless-shell. The Dockerfile looks for either `chrome-headless-shell` or `headless_shell` and symlinks the found binary to `/usr/local/bin/chrome-headless-shell`.

- CI expectations:
  - CI runs ShellCheck on every `scripts/*.sh` file and builds both amd64 and arm64 images, then runs the smoke test against each image. Keep scripts POSIX-compliant and ShellCheck-clean.

- Image usage convention:
  - When running the image locally, prefer using `--user "$(id -u):$(id -g)"` and mounting the project at `-v "$PWD:/project"` so generated files maintain host ownership.

- Windows/WSL2 pointer:
  - See README.md "Windows / WSL2 (ARM) usage" for concise instructions and troubleshooting when running from Windows 11 or WSL2. Using WSL2 (recommended) avoids common path and permission issues.

- Release tagging:
  - Tag names must match `v*` for the publish workflow to run automatically. The publish flow uses docker/metadata-action to generate semver and sha tags.

---

## Important files to inspect when changing build or runtime behavior

- Dockerfile — central build recipe and provenance steps (Kokoro snapshot, third-party sources).
- scripts/smoke_test.sh — authoritative runtime checks used by CI.
- .github/workflows/ci.yml — matrix build & smoke-test steps.
- .github/workflows/publish.yml — buildx publish pipeline, SBOM, provenance and tagging rules.
- README.md — usage examples showing how to run the image with /project mounts.

---

## Guidance for Copilot sessions working in this repo

- Focus on the Dockerfile, smoke tests, and workflows for any change that affects runtime tooling or reproducibility.
- Always run `docker build` and the smoke tests locally for any Dockerfile edit. Use the smoke_test.sh script to validate the specific runtime expectations.
- Be cautious about changing pinned versions (Kokoro revision, HyperFrames, browsers). If changing, ensure the Dockerfile still validates downloaded artifacts and update tests accordingly.
- Preserve multi-arch buildx and cache settings unless replacing them with an equivalent that keeps reproducible builds and cross-arch caching.
- For shell edits, fix ShellCheck warnings locally; CI checks every
  `scripts/*.sh` file.

---

<!-- mermaid-ai-skills:start -->
## Mermaid diagrams

When the user asks to create, edit, or visualize a diagram, follow the
instructions in `.github/instructions/mermaid.instructions.md`.
<!-- mermaid-ai-skills:end -->

---

If any of the above details need expansion (for example, adding a quick `make` wrapper, documenting additional developer scripts, or covering a different CI flow), say which area to expand.
