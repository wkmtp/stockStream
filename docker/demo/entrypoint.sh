#!/bin/bash
# ============================================================
# AI数字人财经直播平台 V4.0 — Demo Entrypoint
# ============================================================
set -e

echo "========================================"
echo " AI Live Demo v4.0.0"
echo " (No GPU, No external APIs, Browser-ready)"
echo "========================================"

export STOCKSTREAM_PLATFORM="${STOCKSTREAM_PLATFORM:-demo}"
export PYTHONPATH="/opt/stockstream:${PYTHONPATH}"

mkdir -p /opt/stockstream/data /opt/stockstream/logs /opt/stockstream/cache

exec "$@"
