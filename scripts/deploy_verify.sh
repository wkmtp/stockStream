#!/bin/bash
# =============================================================================
# StockStream V3.0 — Jetson Xavier NX 部署验证脚本
# =============================================================================
# 使用: bash scripts/deploy_verify.sh
# 输出: deployment_report.md
# =============================================================================

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
PASS=0; FAIL=0; WARN=0

pass() { echo -e "  ${GREEN}[✓]${NC} $1"; PASS=$((PASS + 1)); }
fail() { echo -e "  ${RED}[✗]${NC} $1"; FAIL=$((FAIL + 1)); }
warn() { echo -e "  ${YELLOW}[!]${NC} $1"; WARN=$((WARN + 1)); }

INSTALL_DIR="${STOCKSTREAM_HOME:-/opt/stockstream}"
VENV_DIR="$INSTALL_DIR/.venv"
PY="${VENV_DIR}/bin/python"
TIMESTAMP=$(date -Iseconds)
REPORT="deployment_report.md"

# 写报告
exec > >(tee "$REPORT") 2>&1

cat << 'HEADER'
# StockStream V3.0 部署验证报告

> **目标**: Jetson Xavier NX / Python 3.8 / JetPack 5.x
> **时间**: TIMESTAMP_PLACEHOLDER

HEADER
sed -i "s/TIMESTAMP_PLACEHOLDER/$TIMESTAMP/" "$REPORT" 2>/dev/null || true

echo ""
echo "## 一、环境检测"
echo ""

# ── 1.1 OS ──
if [ -f /etc/os-release ]; then
    . /etc/os-release
    pass "操作系统: $NAME $VERSION"
else
    fail "无法检测操作系统"
fi

# ── 1.2 内核 ──
KERNEL=$(uname -r)
pass "内核版本: $KERNEL"

# ── 1.3 架构 ──
ARCH=$(uname -m)
if [ "$ARCH" = "aarch64" ]; then
    pass "CPU 架构: ARM64 (aarch64) — Jetson 原生"
else
    warn "CPU 架构: $ARCH — 非 ARM64 环境"
fi

# ── 1.4 Jetson / L4T ──
if [ -f /etc/nv_tegra_release ]; then
    L4T=$(head -1 /etc/nv_tegra_release)
    pass "Jetson 平台: $L4T"
else
    warn "非 Jetson 平台 — GPU 推理将回退 CPU 模式"
fi

# ── 1.5 CPU ──
CPU_COUNT=$(nproc)
CPU_MODEL=$(grep "model name" /proc/cpuinfo 2>/dev/null | head -1 | cut -d: -f2- | xargs || echo "ARMv8")
pass "CPU: $CPU_COUNT 核 $CPU_MODEL"

# ── 1.6 内存 ──
MEM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
MEM_MB=$((MEM_KB / 1024))
echo "- 总内存: ${MEM_MB} MB"
if [ "$MEM_MB" -ge 6000 ]; then
    pass "内存: ${MEM_MB} MB (达标 >6GB)"
else
    warn "内存: ${MEM_MB} MB (建议至少 6GB)"
fi

# Swap
SWAP_KB=$(grep SwapTotal /proc/meminfo | awk '{print $2}')
SWAP_MB=$((SWAP_KB / 1024))
echo "- Swap: ${SWAP_MB} MB"
if [ "$SWAP_MB" -ge 4000 ]; then
    pass "Swap: ${SWAP_MB} MB"
else
    warn "Swap: ${SWAP_MB} MB (建议至少 4GB: sudo fallocate -l 6G /swapfile)"
fi

echo ""
echo "## 二、Python 检测"
echo ""

PY38_VER=$(python3.8 --version 2>/dev/null || echo "NOT_FOUND")
if [ "$PY38_VER" != "NOT_FOUND" ]; then
    pass "Python 3.8: $PY38_VER"
else
    fail "Python 3.8 未找到!"
fi

if [ -f "$PY" ]; then
    VENV_PY=$("$PY" --version 2>/dev/null || echo "error")
    pass "虚拟环境: $VENV_DIR ($VENV_PY)"
else
    warn "虚拟环境未创建: $VENV_DIR"
fi

echo ""
echo "## 三、依赖检测"
echo ""

check_pkg() {
    local name="$1"
    if [ -f "$PY" ] && "$PY" -c "import ${2:-$name}" 2>/dev/null; then
        local ver=$("$PY" -c "import ${2:-$name}; print(getattr(${2:-$name}, '__version__', 'ok'))" 2>/dev/null || echo "ok")
        pass "$name: $ver"
    else
        warn "$name 未安装"
    fi
}

check_pkg numpy
check_pkg pandas
check_pkg matplotlib
check_pkg "fastapi"
check_pkg uvicorn
check_pkg "pydantic"
check_pkg "SQLAlchemy" sqlalchemy
check_pkg "httpx"
check_pkg "websockets"
check_pkg "Pillow" PIL
check_pkg "onnxruntime"
check_pkg "opencv-python-headless" cv2
check_pkg "librosa"
check_pkg "soundfile" "soundfile"
check_pkg "APScheduler" apscheduler
check_pkg "plotly"

echo ""
echo "## 四、GPU / 推理检测"
echo ""

if [ -f /etc/nv_tegra_release ]; then
    # ── CUDA ──
    if [ -f /usr/local/cuda/version.txt ]; then
        CUDA_V=$(cat /usr/local/cuda/version.txt | grep -oP '\d+\.\d+')
        pass "CUDA: $CUDA_V"
    elif command -v nvcc &>/dev/null; then
        pass "CUDA: $(nvcc --version | grep -oP 'release \K[\d.]+')"
    else
        warn "CUDA 未检测到"
    fi

    # ── GPU 内存 ──
    if command -v tegrastats &>/dev/null; then
        GPU_INFO=$(timeout 3 tegrastats 2>/dev/null | head -1 || echo "")
        if [ -n "$GPU_INFO" ]; then
            pass "tegrastats 可用"
        fi
    fi

    # ── ONNX Runtime GPU ──
    if [ -f "$PY" ]; then
        "$PY" -c "
import onnxruntime as ort
providers = ort.get_available_providers()
print('ONNX Runtime providers:', providers)
if 'CUDAExecutionProvider' in providers:
    print('GPU_STATUS: CUDA_READY')
elif 'TensorrtExecutionProvider' in providers:
    print('GPU_STATUS: TENSORRT_READY')
else:
    print('GPU_STATUS: CPU_ONLY')
" 2>/dev/null || warn "onnxruntime GPU 检测失败"
    fi
else
    warn "非 Jetson 平台，跳过 GPU 检测"
fi

echo ""
echo "## 五、磁盘检测"
echo ""

DISK_USAGE=$(df -h "$INSTALL_DIR" 2>/dev/null | tail -1 | awk '{print $5" used, "$4" free"}')
echo "- 安装目录: $INSTALL_DIR ($DISK_USAGE)"

DISK_AVAIL=$(df "$INSTALL_DIR" 2>/dev/null | tail -1 | awk '{print $4}')
if [ "$DISK_AVAIL" -gt 10000000 ] 2>/dev/null; then
    pass "磁盘空间充足 (>10GB)"
else
    warn "磁盘空间 <10GB"
fi

echo ""
echo "## 六、端口检测"
echo ""

check_port() {
    local port="$1"
    if ss -tlnp 2>/dev/null | grep -q ":$port " || netstat -tlnp 2>/dev/null | grep -q ":$port "; then
        warn "端口 $port 已被占用"
    else
        pass "端口 $port 可用"
    fi
}

check_port 8080
check_port 9090

echo ""
echo "## 七、文件结构检测"
echo ""

check_dir() { [ -d "$INSTALL_DIR/$1" ] && pass "目录存在: $1" || warn "目录缺失: $1"; }
check_dir "src"
check_dir "stockstream"
check_dir "config"
check_dir "scripts"
check_dir "data"
check_dir "logs"
check_dir "cache"
check_dir "models"

echo ""
echo "## 八、systemd 服务检测"
echo ""

if systemctl is-active ai-live.service &>/dev/null; then
    pass "ai-live.service 运行中"
elif systemctl is-enabled ai-live.service &>/dev/null; then
    pass "ai-live.service 已启用 (未启动)"
elif [ -f /etc/systemd/system/ai-live.service ]; then
    pass "ai-live.service 已安装 (未启用)"
else
    warn "ai-live.service 未安装"
fi

echo ""
echo "## 九、模型文件检测"
echo ""

check_model() {
    local path="$1"; local name="$2"
    if [ -f "$INSTALL_DIR/$path" ]; then
        local size=$(du -h "$INSTALL_DIR/$path" | cut -f1)
        pass "$name: $path ($size)"
    else
        warn "$name 缺失: $path"
    fi
}

check_model "models/face_detector.onnx" "人脸检测"
check_model "models/wav2lip_gan.onnx" "Wav2Lip"
check_model "models/zh_CN-huayan-medium.onnx" "TTS女声"
check_model "models/zh_CN-chaowen-medium.onnx" "TTS男声"

echo ""
echo "## 十、网络检测"
echo ""

if ping -c 1 -W 3 8.8.8.8 > /dev/null 2>&1; then
    pass "外网连通"
else
    warn "外网不通 (可能影响金融数据 API)"
fi

echo ""
echo "## 汇总"
echo ""

TOTAL=$((PASS + FAIL + WARN))
echo "| 状态 | 数量 |"
echo "|------|------|"
echo "| ✓ 通过 | $PASS |"
echo "| ✗ 失败 | $FAIL |"
echo "| ! 警告 | $WARN |"
echo "| **总计** | **$TOTAL** |"
echo ""

if [ "$FAIL" -eq 0 ]; then
    echo "### ✅ 验证通过 — 系统可部署"
else
    echo "### ⚠️ 发现 $FAIL 个失败项，请在部署前修复"
fi

echo ""
echo "---"
echo "*报告生成时间: $TIMESTAMP*"
echo "*目标: Jetson Xavier NX / Python 3.8.10 / JetPack 5.1.x*"

echo ""
echo "验证报告已保存到: $REPORT"
