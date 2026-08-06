# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:0.8.14 AS uv

FROM node:22-bookworm-slim

ARG TARGETARCH
ARG HYPERFRAMES_VERSION=0.7.82
ARG CHROME_HEADLESS_SHELL_VERSION=148.0.7778.167
ARG PUPPETEER_BROWSERS_VERSION=2.13.0
ARG PLAYWRIGHT_VERSION=1.61.1
ARG KOKORO_VERSION=0.9.4
ARG KOKORO_MODEL_REVISION=f3ff3571791e39611d31c381e3a41a3af07b4987
ARG KOKORO_ONNX_VERSION=0.5.0
ARG KOKORO_ONNX_MODEL_VERSION=1.0
ARG KOKORO_ONNX_MODEL_SHA256=7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5
ARG KOKORO_ONNX_VOICES_SHA256=bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d
ARG NPM_REGISTRY=https://registry.npmjs.org
ARG PYPI_INDEX=https://pypi.org/simple

LABEL org.opencontainers.image.title="Skills Video Engine"
LABEL org.opencontainers.image.description="Shared HyperFrames, Kokoro TTS, and FFmpeg generation engine for video skills"
LABEL org.opencontainers.image.source="https://github.com/mhuot/skills-video-engine"
LABEL org.opencontainers.image.documentation="https://github.com/mhuot/skills-video-engine#readme"
LABEL org.opencontainers.image.licenses="MIT"
LABEL io.github.mhuot.skills-video-engine.hyperframes.version="${HYPERFRAMES_VERSION}"
LABEL io.github.mhuot.skills-video-engine.kokoro.version="${KOKORO_VERSION}"
LABEL io.github.mhuot.skills-video-engine.kokoro.model-revision="${KOKORO_MODEL_REVISION}"
LABEL io.github.mhuot.skills-video-engine.browser.amd64.chrome-headless-shell.version="${CHROME_HEADLESS_SHELL_VERSION}"
LABEL io.github.mhuot.skills-video-engine.browser.arm64.playwright.version="${PLAYWRIGHT_VERSION}"

COPY --from=uv /uv /uvx /usr/local/bin/

ENV DEBIAN_FRONTEND=noninteractive \
    PATH="/opt/venv/bin:${PATH}" \
    UV_PYTHON_INSTALL_DIR=/opt/uv-python \
    UV_PYTHON_PREFERENCE=only-managed \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache \
    HF_HOME=/opt/huggingface \
    HF_HUB_OFFLINE=1 \
    HYPERFRAMES_NO_TELEMETRY=1 \
    HYPERFRAMES_PYTHON=/opt/venv/bin/python \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium \
    PRODUCER_HEADLESS_SHELL_PATH=/usr/local/bin/chrome-headless-shell \
    CONTAINER=true

RUN case "${TARGETARCH}" in amd64|arm64) ;; *) echo "Unsupported architecture: ${TARGETARCH}" >&2; exit 1;; esac \
    && sed -i 's/^Types: deb$/Types: deb deb-src/' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        chromium \
        curl \
        dpkg-dev \
        espeak-ng \
        ffmpeg \
        fontconfig \
        fonts-dejavu-core \
        fonts-freefont-ttf \
        fonts-liberation \
        fonts-noto-cjk \
        fonts-noto-color-emoji \
        fonts-noto-core \
        fonts-noto-extra \
        fonts-noto-ui-core \
        libasound2 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libgbm1 \
        libgomp1 \
        libgtk-3-0 \
        libnss3 \
        libpangocairo-1.0-0 \
        libsndfile1 \
        libxcomposite1 \
        libxdamage1 \
        libxrandr2 \
        libxshmfence1 \
        unzip \
    && mkdir -p /usr/src/third-party \
    && cd /usr/src/third-party \
    && apt-get source ffmpeg x264 \
    && apt-get purge -y --auto-remove dpkg-dev \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -fv

RUN if [ "${TARGETARCH}" = "amd64" ]; then \
      npm_config_registry="${NPM_REGISTRY}" npx --yes "@puppeteer/browsers@${PUPPETEER_BROWSERS_VERSION}" install \
        "chrome-headless-shell@${CHROME_HEADLESS_SHELL_VERSION}" \
        --path /opt/chrome; \
    else \
      npm_config_registry="${NPM_REGISTRY}" npx --yes "playwright-core@${PLAYWRIGHT_VERSION}" install chromium-headless-shell; \
    fi \
    && chrome_path="$(find /opt/chrome /opt/ms-playwright \
      \( -name chrome-headless-shell -o -name headless_shell \) -type f 2>/dev/null | head -1)" \
    && test -n "${chrome_path}" \
    && ln -s "${chrome_path}" /usr/local/bin/chrome-headless-shell \
    && npm install --global "hyperframes@${HYPERFRAMES_VERSION}" --registry="${NPM_REGISTRY}" \
    && npm cache clean --force

RUN uv python install 3.12 \
    && uv venv --python 3.12 /opt/venv \
    && UV_DEFAULT_INDEX="${PYPI_INDEX}" uv pip install --python /opt/venv/bin/python \
      "kokoro==${KOKORO_VERSION}" \
      "kokoro-onnx==${KOKORO_ONNX_VERSION}" \
      huggingface-hub \
      numpy \
      soundfile \
    && mkdir -p \
      /tmp/.cache/hyperframes/tts/models \
      /tmp/.cache/hyperframes/tts/voices \
    && curl --fail --location --retry 3 --retry-all-errors \
      "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v${KOKORO_ONNX_MODEL_VERSION}/kokoro-v${KOKORO_ONNX_MODEL_VERSION}.onnx" \
      --output "/tmp/.cache/hyperframes/tts/models/kokoro-v${KOKORO_ONNX_MODEL_VERSION}.onnx" \
    && curl --fail --location --retry 3 --retry-all-errors \
      "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v${KOKORO_ONNX_MODEL_VERSION}/voices-v${KOKORO_ONNX_MODEL_VERSION}.bin" \
      --output "/tmp/.cache/hyperframes/tts/voices/voices-v${KOKORO_ONNX_MODEL_VERSION}.bin" \
    && echo "${KOKORO_ONNX_MODEL_SHA256}  /tmp/.cache/hyperframes/tts/models/kokoro-v${KOKORO_ONNX_MODEL_VERSION}.onnx" | sha256sum --check --strict \
    && echo "${KOKORO_ONNX_VOICES_SHA256}  /tmp/.cache/hyperframes/tts/voices/voices-v${KOKORO_ONNX_MODEL_VERSION}.bin" | sha256sum --check --strict \
    && HF_HUB_OFFLINE=0 python -c "from pathlib import Path; from huggingface_hub import snapshot_download; path = snapshot_download(repo_id='hexgrad/Kokoro-82M', revision='main'); assert Path(path).name == '${KOKORO_MODEL_REVISION}', f'unexpected Kokoro revision: {Path(path).name}'" \
    && python -c "from kokoro import KPipeline; KPipeline(lang_code='a', repo_id='hexgrad/Kokoro-82M')" \
    && hyperframes tts "Container build check" --output /tmp/hyperframes-tts-build-check.wav --json \
    && test -s /tmp/hyperframes-tts-build-check.wav \
    && rm /tmp/hyperframes-tts-build-check.wav \
    && chmod 1777 /tmp/.cache /tmp/.cache/hyperframes /tmp/.cache/hyperframes/tts

RUN rm -rf /tmp/.cache/uv /tmp/.config /tmp/.local \
    && mkdir -p /tmp/.cache /tmp/.config /tmp/.local \
    && chmod 1777 /tmp/.cache /tmp/.config /tmp/.local

WORKDIR /project

CMD ["hyperframes", "--help"]
