# StockStream V3.0 — AI 双数字人财经直播系统 (Production Ready)
# 多阶段构建，支持 x86_64 及 Jetson 基础构建
#
# 构建:  docker build -t stockstream:latest .
# 运行:  docker compose up -d
# 开发:  docker build --target dev -t stockstream:dev .

# ================================================================
# Stage 1: Base — 系统依赖
# ================================================================
FROM python:3.11-slim-bookworm AS base

LABEL maintainer="StockStream Team <stockstream@example.com>"
LABEL version="3.0.0"
LABEL description="AI-powered financial dual-avatar live streaming — Production Ready"
LABEL org.opencontainers.image.source="https://github.com/stockstream/stockstream"
LABEL org.opencontainers.image.version="3.0.0"

# ── 环境变量 ──
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV TZ=Asia/Shanghai

# ── 系统依赖 ──
RUN apt-get update && apt-get install -y --no-install-recommends \
    # 基础工具
    curl wget ca-certificates tzdata \
    # 音频处理
    libsndfile1 libportaudio2 \
    # 视频处理 (FFmpeg 用于编解码和 RTMP 推流)
    ffmpeg \
    libavcodec-extra \
    libavformat-extra \
    # 字体 (matplotlib / Pillow 图表渲染)
    fonts-noto-cjk-extra \
    fonts-liberation \
    # 编译工具 (piper-tts / librosa / onnxruntime)
    build-essential cmake \
    # 数据库
    libsqlite3-0 \
    # 清理
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ── 非 root 用户 ──
RUN groupadd --system stockstream && \
    useradd --system --create-home --shell /bin/bash -g stockstream stockstream && \
    mkdir -p /app /data /app/logs /app/cache /app/backups /app/models && \
    chown -R stockstream:stockstream /app /data

WORKDIR /app

# ================================================================
# Stage 2: Dependencies — Python 依赖安装
# ================================================================
FROM base AS dependencies

COPY requirements.txt .

RUN pip install --upgrade pip setuptools wheel && \
    pip install -r requirements.txt

# ================================================================
# Stage 3: Production (default target)
# ================================================================
FROM base AS production

# ── 复制 Python 依赖 ──
COPY --from=dependencies /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

# ── 复制应用代码 (V3.0 完整目录) ──
COPY --chown=stockstream:stockstream src/       ./src/
COPY --chown=stockstream:stockstream stockstream/ ./stockstream/
COPY --chown=stockstream:stockstream config/     ./config/
COPY --chown=stockstream:stockstream scripts/    ./scripts/

# ── 复制入口脚本 & 版本文件 ──
COPY --chown=stockstream:stockstream src/main.py     ./main.py
COPY --chown=stockstream:stockstream VERSION         ./VERSION
COPY --chown=stockstream:stockstream docker/entrypoint.sh /entrypoint.sh

# ── 创建运行时目录 & 入口脚本可执行 ──
RUN mkdir -p /app/logs /app/data /app/cache /app/backups && \
    chown -R stockstream:stockstream /app/logs /app/data /app/cache /app/backups && \
    chmod +x /entrypoint.sh

# ── 切换到非 root ──
USER stockstream

# ── 入口 ──
ENTRYPOINT ["/entrypoint.sh"]

# ── 健康检查 (V3.0: /health 端点) ──
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8080/health || exit 1

# ── 暴露端口 ──
# 8080: API + 直播页面 + 监控仪表盘
# 9090: Prometheus metrics (可选)
EXPOSE 8080 9090

# ── 启动 ──
CMD ["python", "-u", "main.py"]


# ================================================================
# Stage 4: JetPack (Jetson ARM64 基础) — 由 Dockerfile.jetson 专用
# ================================================================
# 此 stage 保留用于 docker compose --profile jetson 一键构建
# 生产 Jetson 构建请使用: docker build -f Dockerfile.jetson -t stockstream:jetson .
FROM nvcr.io/nvidia/l4t-base:r35.4.1 AS jetpack

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_NO_CACHE_DIR=1
ENV TZ=Asia/Shanghai

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3.10-dev python3-pip \
    curl wget ca-certificates tzdata \
    ffmpeg libsndfile1 libportaudio2 libsqlite3-0 \
    fonts-noto-cjk-extra fonts-liberation \
    build-essential cmake git \
    && apt-get clean && rm -rf /var/lib/apt/lists/* \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.10 1 \
    && update-alternatives --install /usr/bin/pip pip /usr/bin/pip3 1 \
    && groupadd --system stockstream \
    && useradd --system --create-home --shell /bin/bash -g stockstream stockstream \
    && mkdir -p /app /data /app/logs /app/cache /app/backups /app/models \
    && chown -R stockstream:stockstream /app /data

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel && \
    pip install -r requirements.txt && \
    pip install onnxruntime-gpu==1.16.3

COPY --chown=stockstream:stockstream src/         ./src/
COPY --chown=stockstream:stockstream stockstream/ ./stockstream/
COPY --chown=stockstream:stockstream config/      ./config/
COPY --chown=stockstream:stockstream scripts/     ./scripts/
COPY --chown=stockstream:stockstream src/main.py  ./main.py
COPY --chown=stockstream:stockstream VERSION      ./VERSION

RUN mkdir -p /app/logs /app/data /app/cache /app/backups && \
    chown -R stockstream:stockstream /app/logs /app/data /app/cache /app/backups

USER stockstream

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -fsS http://localhost:8080/health || exit 1

EXPOSE 8080 9090
CMD ["python", "-u", "main.py", "--jetson"]


# ================================================================
# Stage 5: Dev — 开发/调试模式
# ================================================================
FROM production AS dev

USER root
RUN pip install debugpy pytest pytest-asyncio pytest-cov watchdog

# 开发模式环境
ENV STOCKSTREAM_ENV=development
ENV STOCKSTREAM_LOG_LEVEL=debug

USER stockstream

CMD ["python", "-m", "debugpy", "--listen", "0.0.0.0:5678", \
     "-m", "uvicorn", "src.web:create_app_factory", \
     "--host", "0.0.0.0", "--port", "8080", "--reload"]
