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

LABEL org.opencontainers.image.title="Skills Video Engine"
LABEL org.opencontainers.image.description="Shared HyperFrames, Kokoro TTS, and FFmpeg generation engine for video skills"
LABEL org.opencontainers.image.source="https://github.com/mhuot/skills-video-engine"
LABEL org.opencontainers.image.documentation="https://github.com/mhuot/skills-video-engine#readme"
LABEL org.opencontainers.image.licenses="MIT"

COPY --from=uv /uv /uvx /usr/local/bin/

ENV DEBIAN_FRONTEND=noninteractive \
    PATH="/opt/venv/bin:${PATH}" \
    UV_PYTHON_INSTALL_DIR=/opt/uv-python \
    UV_PYTHON_PREFERENCE=only-managed \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache \
    HF_HOME=/opt/huggingface \
    HF_HUB_OFFLINE=1 \
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
      npx --yes "@puppeteer/browsers@${PUPPETEER_BROWSERS_VERSION}" install \
        "chrome-headless-shell@${CHROME_HEADLESS_SHELL_VERSION}" \
        --path /opt/chrome; \
    else \
      npx --yes "playwright-core@${PLAYWRIGHT_VERSION}" install chromium-headless-shell; \
    fi \
    && chrome_path="$(find /opt/chrome /opt/ms-playwright \
      \( -name chrome-headless-shell -o -name headless_shell \) -type f 2>/dev/null | head -1)" \
    && test -n "${chrome_path}" \
    && ln -s "${chrome_path}" /usr/local/bin/chrome-headless-shell \
    && npm install --global "hyperframes@${HYPERFRAMES_VERSION}" \
    && npm cache clean --force

RUN uv python install 3.12 \
    && uv venv --python 3.12 /opt/venv \
    && uv pip install --python /opt/venv/bin/python \
      "kokoro==${KOKORO_VERSION}" \
      huggingface-hub \
      numpy \
      soundfile \
    && HF_HUB_OFFLINE=0 python -c "from pathlib import Path; from huggingface_hub import snapshot_download; path = snapshot_download(repo_id='hexgrad/Kokoro-82M', revision='main'); assert Path(path).name == '${KOKORO_MODEL_REVISION}', f'unexpected Kokoro revision: {Path(path).name}'" \
    && python -c "from kokoro import KPipeline; KPipeline(lang_code='a', repo_id='hexgrad/Kokoro-82M')"

WORKDIR /project

CMD ["hyperframes", "--help"]
