# StockStream v2.0 — 企业级 AI 数字人财经直播系统
# 多阶段构建，支持 Jetson Xavier NX (ARM64) 和 x86_64

# ── Stage 1: Base ────────────────────────────────────────────────────────
FROM python:3.11-slim-bookworm AS base

LABEL maintainer="StockStream Team"
LABEL version="1.0.0"
LABEL description="AI-powered financial live streaming system"

# 防止交互式安装
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    # 基础工具
    curl \
    wget \
    ca-certificates \
    # 音频处理
    libsndfile1 \
    libportaudio2 \
    # 视频处理
    ffmpeg \
    libavcodec-extra \
    libavformat-extra \
    # 数据库
    libsqlite3-0 \
    # 编译工具 (for piper-tts / onnxruntime)
    build-essential \
    cmake \
    # 清理
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 创建非 root 用户
RUN useradd --create-home --shell /bin/bash stockstream && \
    mkdir -p /app /data /app/logs /app/cache && \
    chown -R stockstream:stockstream /app /data

WORKDIR /app

# ── Stage 2: Dependencies ─────────────────────────────────────────────────
FROM base AS dependencies

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --upgrade pip setuptools wheel && \
    pip install -r requirements.txt

# ── Stage 3: Production ───────────────────────────────────────────────────
FROM base AS production

# 复制 Python 包
COPY --from=dependencies /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

# 复制应用代码
COPY --chown=stockstream:stockstream src/ ./src/
COPY --chown=stockstream:stockstream config/ ./config/
COPY --chown=stockstream:stockstream stockstream/ ./stockstream/

# 复制入口脚本
COPY --chown=stockstream:stockstream src/main.py ./main.py

# 切换到非 root 用户
USER stockstream

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/api/v2/health || exit 1

# 暴露端口
EXPOSE 8000 9090

# 启动命令
CMD ["python", "-u", "main.py"]


# ── Stage 4: Jetson (ARM64) ───────────────────────────────────────────────
FROM base AS jetson

# Jetson 特定系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Jetson 工具
    nvidia-jetpack \
    libnvinfer8 \
    libnvinfer-plugin8 \
    # 清理
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 安装 Jetson 优化的 onnxruntime
COPY --from=dependencies /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
RUN pip install onnxruntime-gpu==1.16.3

# 复制应用代码
COPY --chown=stockstream:stockstream src/ ./src/
COPY --chown=stockstream:stockstream config/ ./config/
COPY --chown=stockstream:stockstream src/main.py ./main.py

# GPU 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import onnxruntime; print(onnxruntime.get_device())" || exit 1

USER stockstream
EXPOSE 8000 9090
CMD ["python", "-u", "main.py"]


# ── Stage 5: Dev ──────────────────────────────────────────────────────────
FROM production AS dev

USER root
RUN pip install debugpy pytest pytest-asyncio pytest-cov
USER stockstream

# 开发模式热重载
ENV STOCKSTREAM_ENV=development
CMD ["python", "-m", "debugpy", "--listen", "0.0.0.0:5678", "-m", "uvicorn", "src.web:create_app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
