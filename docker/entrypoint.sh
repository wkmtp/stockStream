#!/bin/bash
# StockStream V3.0 — Docker Entrypoint Script
# 容器启动时自动执行初始化任务
#
# 功能:
#   1. 等待依赖服务就绪 (Redis / PostgreSQL)
#   2. 数据库迁移 (auto_migrate)
#   3. 模型文件检查
#   4. 目录权限修复
#   5. 启动应用

set -euo pipefail

APP_DIR="/app"
DATA_DIR="${APP_DIR}/data"
LOG_DIR="${APP_DIR}/logs"
CACHE_DIR="${APP_DIR}/cache"
BACKUP_DIR="${APP_DIR}/backups"

echo "════════════════════════════════════════════════════════════"
echo "  StockStream V3.0 — Container Bootstrap"
echo "  Version: $(cat ${APP_DIR}/VERSION 2>/dev/null || echo 'unknown')"
echo "  Started: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "════════════════════════════════════════════════════════════"

# ── 1. 创建 & 修复运行时目录 ──
echo "[init] Ensuring runtime directories..."
mkdir -p "${DATA_DIR}" "${LOG_DIR}" "${CACHE_DIR}" "${BACKUP_DIR}"
chmod 755 "${DATA_DIR}" "${LOG_DIR}" "${CACHE_DIR}" "${BACKUP_DIR}"

# ── 2. 等待 Redis (如果配置) ──
if [[ -n "${REDIS_URL:-}" ]] && command -v redis-cli &>/dev/null; then
    REDIS_HOST=$(echo "${REDIS_URL}" | sed -E 's|redis://([^:/]+).*|\1|')
    REDIS_PORT=$(echo "${REDIS_URL}" | sed -E 's|.*:([0-9]+).*|\1|')
    echo "[init] Waiting for Redis at ${REDIS_HOST}:${REDIS_PORT}..."
    for i in $(seq 1 30); do
        if redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT:-6379}" ping &>/dev/null; then
            echo "[init] Redis ready."
            break
        fi
        echo "  Retry ${i}/30..."
        sleep 2
    done
fi

# ── 3. 等待 PostgreSQL (如果配置) ──
if [[ -n "${DATABASE_URL:-}" ]] && [[ "${DATABASE_URL}" == postgresql* ]]; then
    echo "[init] Checking PostgreSQL connection..."
    # pg_isready 通常已安装; 如果没有则跳过
    if command -v pg_isready &>/dev/null; then
        PG_HOST=$(echo "${DATABASE_URL}" | sed -E 's|.*@([^:/]+).*|\1|')
        for i in $(seq 1 30); do
            if pg_isready -h "${PG_HOST}" &>/dev/null; then
                echo "[init] PostgreSQL ready."
                break
            fi
            echo "  Retry ${i}/30..."
            sleep 2
        done
    fi
fi

# ── 4. 模型文件检查 ──
echo "[init] Checking model files..."
MODELS_FOUND=0
for model_file in "${APP_DIR}/models"/*.onnx; do
    if [[ -f "${model_file}" ]]; then
        MODELS_FOUND=$((MODELS_FOUND + 1))
        model_name=$(basename "${model_file}")
        model_size=$(du -h "${model_file}" 2>/dev/null | cut -f1 || echo "?")
        echo "  Found: ${model_name} (${model_size})"
    fi
done
if [[ ${MODELS_FOUND} -eq 0 ]]; then
    echo "  [WARN] No ONNX model files found in ${APP_DIR}/models/"
    echo "  Expected: zh_CN-huayan-medium.onnx, zh_CN-chaowen-medium.onnx, face_detector.onnx"
    echo "  Run: python scripts/download_models.py --tts --face"
fi

# ── 5. 数据库初始化 (SQLite WAL 模式) ──
if [[ -f "${DATA_DIR}/stockstream.db" ]]; then
    echo "[init] Existing database found at ${DATA_DIR}/stockstream.db"
    # 启用 WAL 模式 (持久化)
    sqlite3 "${DATA_DIR}/stockstream.db" "PRAGMA journal_mode=WAL;" 2>/dev/null || true
    echo "[init] Database WAL mode: $(sqlite3 "${DATA_DIR}/stockstream.db" "PRAGMA journal_mode;" 2>/dev/null || echo 'N/A')"
else
    echo "[init] No existing database. Will be auto-created on first run."
fi

# ── 6. 清理过期缓存 ──
echo "[init] Cleaning stale cache files (older than 24h)..."
find "${CACHE_DIR}" -type f -mtime +1 -delete 2>/dev/null || true

# ── 7. 启动应用 ──
echo "[init] Starting StockStream application..."
echo "════════════════════════════════════════════════════════════"

exec "$@"
