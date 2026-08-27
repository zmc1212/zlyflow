# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS frontend-builder

ARG NPM_CONFIG_REGISTRY=https://registry.npmmirror.com

ENV NPM_CONFIG_REGISTRY=${NPM_CONFIG_REGISTRY} \
    COREPACK_NPM_REGISTRY=${NPM_CONFIG_REGISTRY}

WORKDIR /build
RUN corepack enable

COPY pnpm-lock.yaml pnpm-workspace.yaml ./
COPY frontend/package.json frontend/package.json
RUN pnpm install --frozen-lockfile --filter zly-ai-video-studio-webui...

COPY frontend frontend
RUN pnpm --filter zly-ai-video-studio-webui build


FROM python:3.11-slim-bookworm AS runtime

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    ZLY_AI_VIDEO_STUDIO_WORKBENCH_PORT=18189 \
    ZLY_AI_VIDEO_STUDIO_DATA_DIR=/var/lib/zly-ai-video-studio

WORKDIR /app

COPY backend/requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir --prefer-binary -r /tmp/requirements.txt \
    && addgroup --system zlyai \
    && adduser --system --ingroup zlyai --home /app zlyai \
    && mkdir -p /var/lib/zly-ai-video-studio /app/results \
    && chown -R zlyai:zlyai /var/lib/zly-ai-video-studio /app/results

COPY backend backend
COPY local_video_studio.py local_video_studio.py
COPY --from=frontend-builder /build/frontend/dist frontend/dist

USER zlyai
EXPOSE 18189
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c 'import os, urllib.request; urllib.request.urlopen("http://127.0.0.1:" + os.environ["ZLY_AI_VIDEO_STUDIO_WORKBENCH_PORT"] + "/api/health", timeout=3)'

CMD ["sh", "-c", "python -m uvicorn backend.app.main:app --host 0.0.0.0 --port $ZLY_AI_VIDEO_STUDIO_WORKBENCH_PORT"]
