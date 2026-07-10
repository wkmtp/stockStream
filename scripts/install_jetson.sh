#!/bin/bash
# =============================================================================
# StockStream V3.0 — Jetson Xavier NX LTS 安装脚本
# =============================================================================
#
# 使用:  sudo bash scripts/install_jetson.sh
#
# 功能:
#   1. 自动检测 Python 3.8 / CUDA / TensorRT / JetPack 版本
#   2. 安装系统依赖 (ffmpeg, libsndfile, espeak-ng 等)
#   3. 创建 Python 3.8 虚拟环境并安装 requirements-jetson.txt
#   4. 安装 ONNX Runtime GPU (JetPack 5.1.x 适配)
#   5. 安装 systemd 服务并启用开机自启动
#   6. 输出部署验证报告
#
# 要求: Ubuntu 20.04 + JetPack 5.x + Python 3.8
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log()   { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[✗]${NC} $1"; }
info()  { echo -e "${BLUE}[→]${NC} $1"; }

INSTALL_DIR="/opt/stockstream"
VENV_DIR="$INSTALL_DIR/.venv"
SVC_USER="stockstream"

# =============================================================================
# Step 0: 权限检查
# =============================================================================
if [ "$EUID" -ne 0 ]; then
    error "请使用 sudo 运行此脚本"
    exit 1
fi

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║   StockStream V3.0 — Jetson Xavier NX LTS 安装脚本          ║"
echo "║   目标: Python 3.8 / CUDA 11.4 / TensorRT 8.x / ARM64       ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# =============================================================================
# Step 1: 环境检测
# =============================================================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " [1/8] 环境检测"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1a. Python 版本 ──
PYTHON_VER=$(python3.8 --version 2>/dev/null || echo "NOT_FOUND")
if [ "$PYTHON_VER" = "NOT_FOUND" ]; then
    error "Python 3.8 未找到! 请先安装: sudo apt-get install python3.8 python3.8-dev python3.8-distutils"
    exit 1
fi
log "Python: $PYTHON_VER"

# ── 1b. JetPack / L4T 版本 ──
if [ -f /etc/nv_tegra_release ]; then
    L4T_VER=$(head -1 /etc/nv_tegra_release 2>/dev/null | grep -oP 'R\d+\.\d+\.\d+' || echo "unknown")
    log "L4T: $L4T_VER"
else
    warn "非 Jetson 平台 (/etc/nv_tegra_release 未找到), GPU 功能将不可用"
    L4T_VER="N/A"
fi

# ── 1c. CUDA ──
CUDA_VER="NOT_FOUND"
if [ -f /usr/local/cuda/version.txt ]; then
    CUDA_VER=$(cat /usr/local/cuda/version.txt 2>/dev/null | grep -oP '\d+\.\d+' || echo "unknown")
    log "CUDA: $CUDA_VER"
elif command -v nvcc &>/dev/null; then
    CUDA_VER=$(nvcc --version 2>/dev/null | grep -oP 'release \K\d+\.\d+' || echo "unknown")
    log "CUDA: $CUDA_VER (via nvcc)"
else
    warn "CUDA 未检测到 — GPU 推理将回退到 CPU 模式"
fi

# ── 1d. TensorRT ──
TRT_VER="NOT_FOUND"
if python3.8 -c "import tensorrt" 2>/dev/null; then
    TRT_VER=$(python3.8 -c "import tensorrt; print(tensorrt.__version__)" 2>/dev/null || echo "unknown")
    log "TensorRT: $TRT_VER"
elif dpkg -l | grep -q tensorrt 2>/dev/null; then
    TRT_VER=$(dpkg -l | grep tensorrt | head -1 | awk '{print $3}' || echo "installed")
    log "TensorRT: $TRT_VER (系统包)"
else
    warn "TensorRT 未检测到 — 将以 CPU EP 运行 ONNX Runtime"
fi

# ── 1e. 内存 ──
MEM_KB=$(grep MemTotal /proc/meminfo 2>/dev/null | awk '{print $2}' || echo 0)
MEM_MB=$((MEM_KB / 1024))
info "系统内存: ${MEM_MB} MB"

if [ "$MEM_MB" -lt 6000 ]; then
    warn "内存 < 6GB，建议添加 swap: sudo fallocate -l 6G /swapfile"
fi

# ── 1f. 架构 ──
ARCH=$(uname -m)
info "CPU 架构: $ARCH"
if [ "$ARCH" != "aarch64" ] && [ "$ARCH" != "armv7l" ]; then
    warn "非 ARM64 架构 ($ARCH)，此为 x86 开发环境"
fi

# =============================================================================
# Step 2: 安装系统依赖
# =============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " [2/8] 安装系统依赖"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

apt-get update -qq

PACKAGES=(
    python3.8 python3.8-dev python3.8-distutils python3.8-venv
    python3-pip
    ffmpeg
    libsndfile1 libportaudio2
    libsqlite3-0
    fonts-noto-cjk-extra fonts-liberation
    build-essential cmake
    curl wget ca-certificates
    espeak-ng
    libopenblas-dev libatlas-base-dev
)

for pkg in "${PACKAGES[@]}"; do
    if dpkg -l | grep -q "^ii.*$pkg "; then
        info "$pkg 已安装, 跳过"
    else
        info "安装 $pkg..."
        apt-get install -y --no-install-recommends "$pkg" > /dev/null 2>&1
        log "$pkg 安装完成"
    fi
done

# =============================================================================
# Step 3: 创建运行时用户
# =============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " [3/8] 创建运行时用户"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if ! id "$SVC_USER" &>/dev/null; then
    groupadd --system "$SVC_USER" 2>/dev/null || true
    useradd --system --create-home --shell /bin/bash -g "$SVC_USER" "$SVC_USER"
    log "已创建用户: $SVC_USER"
else
    info "用户 $SVC_USER 已存在"
fi

# =============================================================================
# Step 4: 部署项目代码
# =============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " [4/8] 部署项目代码"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

if [ "$PROJECT_ROOT" != "$INSTALL_DIR" ]; then
    info "从 $PROJECT_ROOT 复制到 $INSTALL_DIR ..."
    mkdir -p "$INSTALL_DIR"
    rsync -a --exclude='.venv' --exclude='__pycache__' --exclude='*.pyc' \
          --exclude='.git' --exclude='cache/*' --exclude='logs/*' \
          "$PROJECT_ROOT/" "$INSTALL_DIR/"
    log "项目代码已复制到 $INSTALL_DIR"
else
    info "项目已在 $INSTALL_DIR，跳过复制"
fi

chown -R "$SVC_USER:$SVC_USER" "$INSTALL_DIR"

# =============================================================================
# Step 5: 创建虚拟环境 & 安装 Python 依赖
# =============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " [5/8] Python 3.8 虚拟环境 + 依赖安装"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

cd "$INSTALL_DIR"

if [ -d "$VENV_DIR" ]; then
    warn "虚拟环境已存在，重新创建..."
    rm -rf "$VENV_DIR"
fi

sudo -u "$SVC_USER" python3.8 -m venv "$VENV_DIR"
log "Python 3.8 虚拟环境已创建: $VENV_DIR"

sudo -u "$SVC_USER" "$VENV_DIR/bin/pip" install --upgrade \
    pip==23.0.1 setuptools==68.0.0 wheel==0.41.3
log "pip/setuptools/wheel 已升级"

sudo -u "$SVC_USER" "$VENV_DIR/bin/pip" install -r requirements-jetson.txt
log "Python 依赖已安装 (requirements-jetson.txt)"

# ── Jetson GPU: 安装 ONNX Runtime GPU ──
if [ "$ARCH" = "aarch64" ] && [ -f /etc/nv_tegra_release ]; then
    info "检测到 Jetson 平台, 安装 onnxruntime-gpu 1.16.3..."
    sudo -u "$SVC_USER" "$VENV_DIR/bin/pip" install onnxruntime-gpu==1.16.3 2>/dev/null || \
        warn "onnxruntime-gpu 安装失败 (可能需手动安装): pip install onnxruntime-gpu==1.16.3"
else
    info "x86 环境, 使用 onnxruntime CPU 版本"
fi

# =============================================================================
# Step 6: 创建运行时目录 & 配置文件
# =============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " [6/8] 创建运行时目录 & 配置"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

sudo -u "$SVC_USER" mkdir -p \
    "$INSTALL_DIR/data" \
    "$INSTALL_DIR/logs" \
    "$INSTALL_DIR/cache/trt_engines" \
    "$INSTALL_DIR/backups" \
    "$INSTALL_DIR/models"

# 创建默认 .env
if [ ! -f "$INSTALL_DIR/.env" ]; then
    cat > "$INSTALL_DIR/.env" << 'ENVEOF'
# StockStream V3.0 Jetson Xavier NX 环境变量
STOCKSTREAM_HOST=0.0.0.0
STOCKSTREAM_PORT=8080
STOCKSTREAM_LOG_LEVEL=info
STOCKSTREAM_JETSON_MODE=1
STOCKSTREAM_ENV=production
STOCKSTREAM_MAX_MEMORY_MB=6144
STOCKSTREAM_TENSORRT_ENABLED=false
STOCKSTREAM_MARKET__POLL_SECONDS=5
STOCKSTREAM_MARKET__SYMBOLS=sh000001,sz399001,sz399006
STOCKSTREAM_TTS__VOICE=zh_CN-huayan-medium
STOCKSTREAM_DATABASE__URL=sqlite+aiosqlite:///data/stockstream.db
STOCKSTREAM_AVATAR__ENABLED=true
STOCKSTREAM_AVATAR__FPS=25
STOCKSTREAM_DEEPSEEK_API_KEY=
STOCKSTREAM_STREAM__RTMP_URL=
ENVEOF
    chown "$SVC_USER:$SVC_USER" "$INSTALL_DIR/.env"
    chmod 600 "$INSTALL_DIR/.env"
    log "默认 .env 已创建 (请填入 STOCKSTREAM_DEEPSEEK_API_KEY)"
fi

# =============================================================================
# Step 7: 安装 systemd 服务
# =============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " [7/8] 安装 systemd 服务"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

cp "$INSTALL_DIR/services/ai-live.service" /etc/systemd/system/ai-live.service
chmod 644 /etc/systemd/system/ai-live.service
systemctl daemon-reload
log "systemd 服务文件已安装"

# 检查是否应启用
read -p "启用开机自启动? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    systemctl enable ai-live.service
    log "已启用开机自启动"
else
    info "跳过开机自启动 (之后可执行: sudo systemctl enable ai-live)"
fi

# =============================================================================
# Step 8: 部署验证
# =============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " [8/8] 部署验证"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

PASS=0
FAIL=0
check() {
    local desc="$1"; shift
    if "$@" > /dev/null 2>&1; then
        log "$desc"
        PASS=$((PASS + 1))
    else
        warn "$desc"
        FAIL=$((FAIL + 1))
    fi
}

echo ""
check "Python 3.8 可用"       python3.8 --version
check "虚拟环境存在"           test -f "$VENV_DIR/bin/python"
check "pip 可用"               "$VENV_DIR/bin/pip" --version
check "numpy 已安装"           "$VENV_DIR/bin/python" -c "import numpy"
check "pandas 已安装"          "$VENV_DIR/bin/python" -c "import pandas"
check "fastapi 已安装"         "$VENV_DIR/bin/python" -c "import fastapi"
check "uvicorn 已安装"         "$VENV_DIR/bin/python" -c "import uvicorn"
check "matplotlib 已安装"      "$VENV_DIR/bin/python" -c "import matplotlib"
check "onnxruntime 已安装"     "$VENV_DIR/bin/python" -c "import onnxruntime"
check "systemd 服务已安装"     test -f /etc/systemd/system/ai-live.service
check "用户存在"               id "$SVC_USER" &>/dev/null
check "工作目录存在"           test -d "$INSTALL_DIR"
check "Env文件存在"            test -f "$INSTALL_DIR/.env"

echo ""
echo "──────────────────────────────────────────────────────────"
echo "  总计: $((PASS + FAIL)) 检测项 | ${GREEN}通过 $PASS${NC} | ${RED}失败 $FAIL${NC} (非关键)"
echo "──────────────────────────────────────────────────────────"

# ── GPU 专项检测 ──
if [ "$ARCH" = "aarch64" ] && [ -f /etc/nv_tegra_release ]; then
    echo ""
    echo "── GPU/推理 专项检测 ──"
    "$VENV_DIR/bin/python" -c "
import sys
print('ONNX Runtime 可用 Providers:')
try:
    import onnxruntime as ort
    providers = ort.get_available_providers()
    for p in providers:
        print(f'  - {p}')
    if 'CUDAExecutionProvider' in providers:
        print('  ✓ CUDA GPU 推理可用')
    elif 'TensorrtExecutionProvider' in providers:
        print('  ✓ TensorRT GPU 推理可用')
    else:
        print('  ! GPU EP 不可用 — 将使用 CPU 推理')
except Exception as e:
    print(f'  ✗ onnxruntime 导入失败: {e}')
" 2>/dev/null || warn "GPU 检测子进程失败"
fi

# =============================================================================
# 完成
# =============================================================================
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                    安装完成!                                 ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  启动服务:   sudo systemctl start ai-live                    ║"
echo "║  停止服务:   sudo systemctl stop ai-live                     ║"
echo "║  查看状态:   sudo systemctl status ai-live                   ║"
echo "║  查看日志:   sudo journalctl -u ai-live -f                   ║"
echo "║  重启服务:   sudo systemctl restart ai-live                  ║"
echo "║  健康检查:   curl http://localhost:8080/health               ║"
echo "║  API 文档:   http://localhost:8080/docs                      ║"
echo "║  直播页面:   http://localhost:8080/live                      ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  首次启动前请确认:                                           ║"
echo "║  1. 编辑 $INSTALL_DIR/.env     ║"
echo "║  2. 填入 STOCKSTREAM_DEEPSEEK_API_KEY (DeepSeek API Key)    ║"
echo "║  3. 下载模型: .venv/bin/python scripts/download_models.py   ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
