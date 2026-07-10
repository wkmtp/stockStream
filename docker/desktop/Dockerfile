# ============================================================
# AI数字人财经直播平台 V4.0 — Desktop Docker 镜像
# ============================================================
# 目标:   Windows / Linux Desktop + NVIDIA RTX GPU
# CUDA:   12.4
# Python: 3.11
# 用法:
#   docker build -f docker/desktop/Dockerfile -t ai-live-desktop .
#   docker compose -f docker/desktop/docker-compose.yml up

FROM nvidia/cuda:12.4.0-runtime-ubuntu22.04

LABEL maintainer="AI Live Platform Team"
LABEL version="4.0.0-enterprise"
LABEL variant="desktop"
LABEL description="AI FinTech Live — Desktop Production Edition"

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# ── 系统依赖 ──
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3.11-dev python3.11-venv \
    ffmpeg \
    libsndfile1 libopenblas-dev \
    libgl1-mesa-glx libglib2.0-0 \
    curl ca-certificates \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ── 创建非 root 用户 ──
RUN groupadd -r stockstream && useradd -r -g stockstream -m -s /bin/bash stockstream

# ── Python 环境 ──
RUN python3.11 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# ── 应用目录 ──
WORKDIR /opt/stockstream
RUN mkdir -p data logs cache models && chown -R stockstream:stockstream /opt/stockstream

# ── 依赖安装 ──
COPY requirements/common.txt requirements/
COPY requirements/desktop.txt requirements/
RUN pip install --upgrade pip setuptools wheel && \
    pip install -r requirements/common.txt -r requirements/desktop.txt

# ── 源码 ──
COPY src/ src/
COPY configs/ configs/
COPY docker/desktop/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER stockstream

EXPOSE 8080 9090

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "src.main"]
