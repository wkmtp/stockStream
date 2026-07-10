#!/bin/bash
# ============================================================
# AI数字人财经直播平台 V4.0 — Desktop Entrypoint
# ============================================================
set -e

echo "=== AI Live Desktop v4.0.0 ==="
echo "Platform: $(uname -m)"
echo "Python:   $(python3 --version)"
echo "CUDA:     $(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null || echo 'N/A')"

# ── 环境检测 ──
export STOCKSTREAM_PLATFORM="${STOCKSTREAM_PLATFORM:-desktop}"
export PYTHONPATH="/opt/stockstream:${PYTHONPATH}"

# ── 目录准备 ──
mkdir -p /opt/stockstream/data /opt/stockstream/logs /opt/stockstream/cache

exec "$@"
