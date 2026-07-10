# ============================================================
# AI数字人财经直播平台 V4.0 — Demo Docker 镜像
# ============================================================
# 目标:   纯 CPU 演示模式
# Python: 3.11 (slim)
# 用法:
#   docker build -f docker/demo/Dockerfile -t ai-live-demo .

FROM python:3.11-slim

LABEL maintainer="AI Live Platform Team"
LABEL version="4.0.0-enterprise"
LABEL variant="demo"
LABEL description="AI FinTech Live — Demo Edition (zero external deps)"

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_NO_CACHE_DIR=1

# ── 系统依赖 ──
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    libgl1-mesa-glx libglib2.0-0 \
    curl ca-certificates \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ── 用户 ──
RUN groupadd -r stockstream && useradd -r -g stockstream -m -s /bin/bash stockstream

# ── 应用 ──
WORKDIR /opt/stockstream
RUN mkdir -p data logs cache && chown -R stockstream:stockstream /opt/stockstream

# ── 依赖 ──
COPY requirements/common.txt requirements/
COPY requirements/demo.txt requirements/
RUN pip install -r requirements/common.txt -r requirements/demo.txt

# ── 源码 ──
COPY src/ src/
COPY configs/ configs/
COPY docker/demo/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER stockstream

EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "src.main"]
