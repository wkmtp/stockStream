#!/bin/bash
# ============================================================
# AI数字人财经直播平台 V4.0 — Jetson Entrypoint
# ============================================================
set -e

echo "========================================"
echo " AI Live Jetson Xavier NX v4.0.0"
echo "========================================"
echo "Board:    $(cat /proc/device-tree/model 2>/dev/null || echo 'Jetson Xavier NX')"
echo "L4T:      $(dpkg-query --showformat='${Version}' --show nvidia-l4t-core 2>/dev/null || echo 'N/A')"
echo "JetPack:  $(apt-cache policy nvidia-jetpack 2>/dev/null | grep Installed | awk '{print $2}' || echo 'N/A')"
echo "CUDA:     $(nvcc --version 2>/dev/null | grep 'release' | awk '{print $5}' | tr -d ',' || echo 'N/A')"
echo "Python:   $(python3 --version)"
echo "Arch:     $(uname -m)"
echo "Mem:      $(free -h | grep Mem | awk '{print $2}')"
echo "========================================"

# ── 环境 ──
export STOCKSTREAM_PLATFORM="${STOCKSTREAM_PLATFORM:-jetson}"
export STOCKSTREAM_JETSON_MODE=1
export PYTHONPATH="/opt/stockstream:${PYTHONPATH}"

# ── Jetson 性能调优 ──
# 设置最大时钟 (需要 root, entrypoint 在 root 下执行)
if [ "$(id -u)" = "0" ]; then
    nvpmodel -m 2 2>/dev/null || true   # 10W 模式
    jetson_clocks 2>/dev/null || true
fi

# ── 目录 ──
mkdir -p /opt/stockstream/data /opt/stockstream/logs /opt/stockstream/cache/trt_engines

# ── 切换用户 ──
if [ "$(id -u)" = "0" ]; then
    chown -R stockstream:stockstream /opt/stockstream
    exec gosu stockstream "$@"
else
    exec "$@"
fi
