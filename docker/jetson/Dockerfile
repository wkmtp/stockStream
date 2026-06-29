# ============================================================
# AI数字人财经直播平台 V4.0 — Jetson Xavier NX Docker 镜像
# ============================================================
# 目标:   NVIDIA Jetson Xavier NX 8GB + JetPack 5.x
# CUDA:   11.4
# TensorRT: 8.x
# Python: 3.8 (L4T 系统原生)
# 用法:
#   docker build -f docker/jetson/Dockerfile -t ai-live-jetson .

# ── NVIDIA L4T + JetPack 5.1.2 为基础 ──
# nvcr.io 镜像自带 CUDA 11.4 / TensorRT 8.5 / OpenCV 4.5
FROM nvcr.io/nvidia/l4t-base:r35.4.1

LABEL maintainer="AI Live Platform Team"
LABEL version="4.0.0-enterprise"
LABEL variant="jetson-xavier-nx"
LABEL description="AI FinTech Live — Jetson Xavier NX Production Edition"

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# ── 系统依赖 (ARM64) ──
# 注意: CUDA 11.4 / cuDNN 8.6 / TensorRT 8.5 已预装在 l4t-base 镜像中,
#       不要尝试 apt install nvidia-l4t-* / nvidia-jetpack 等包, 它们不存在或无需单独安装.
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.8 python3.8-dev python3.8-venv \
    python3-pip \
    ffmpeg \
    libsndfile1 libopenblas-dev \
    libopenmpi-dev \
    libopencv-dev python3-opencv \
    curl ca-certificates htop \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ── Python 符号链接 ──
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.8 1 && \
    python3.8 -m pip install --upgrade pip setuptools wheel

# ── 创建用户 ──
RUN groupadd -r stockstream && useradd -r -g stockstream -m -s /bin/bash stockstream

# ── 应用目录 ──
WORKDIR /opt/stockstream
RUN mkdir -p data logs cache models && chown -R stockstream:stockstream /opt/stockstream

# ── 依赖安装 ──
COPY requirements/common.txt requirements/
COPY requirements/jetson.txt requirements/
RUN pip3 install -r requirements/common.txt -r requirements/jetson.txt

# ── ONNX Runtime GPU (Jetson ARM64 wheel) ──
#  预编译 wheel 已通过 NVIDIA SDK Manager 安装，此处从系统路径引用
#  RUN pip3 install https://github.com/microsoft/onnxruntime/releases/download/v1.16.3/onnxruntime_gpu-1.16.3-cp38-cp38-linux_aarch64.whl

# ── 源码 ──
COPY src/ src/
COPY configs/ configs/
COPY docker/jetson/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# ── Jetson 加速 ──
ENV OPENBLAS_CORETYPE=ARMV8
ENV OMP_NUM_THREADS=4
ENV MKL_NUM_THREADS=4
ENV ORT_TENSORRT_FP16_ENABLE=1
ENV ORT_TENSORRT_ENGINE_CACHE_ENABLE=1
ENV ORT_TENSORRT_ENGINE_CACHE_PATH=/opt/stockstream/cache/trt_engines

USER stockstream

EXPOSE 8080 9090

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python3", "-m", "src.main"]
