#!/bin/bash
# StockStream V3.0 systemd 安装脚本
# 使用方法: sudo bash services/install.sh
#
# 前置条件: 项目代码已复制到 /opt/stockstream，依赖已安装
#   sudo cp -r . /opt/stockstream
#   cd /opt/stockstream
#   python3.10 -m venv .venv
#   .venv/bin/pip install -r requirements.txt
#   # Jetson: .venv/bin/pip install onnxruntime-gpu==1.16.3
#   sudo bash services/install.sh

set -e

echo "=== StockStream V3.0 systemd 安装 ==="

# 检查是否为 root
if [ "$EUID" -ne 0 ]; then
    echo "错误: 请使用 sudo 运行此脚本"
    exit 1
fi

SERVICE_FILE="ai-live.service"
INSTALL_DIR="/opt/stockstream"
SYSTEMD_DIR="/etc/systemd/system"
SVC_USER="stockstream"

# ── Step 1: 创建运行时用户 (如果不存在) ──
echo "[1/6] 检查运行时用户..."
if ! id "$SVC_USER" &>/dev/null; then
    groupadd --system "$SVC_USER" 2>/dev/null || true
    useradd --system --create-home --shell /bin/bash -g "$SVC_USER" "$SVC_USER"
    echo "  -> 已创建用户: $SVC_USER"
else
    echo "  -> 用户 $SVC_USER 已存在"
fi

# ── Step 2: 创建运行时目录 ──
echo "[2/6] 创建运行时目录..."
mkdir -p "$INSTALL_DIR"/{data,logs,cache,backups,config}
chown -R "$SVC_USER:$SVC_USER" "$INSTALL_DIR"

# ── Step 3: 复制 & 修正 systemd 服务文件 ──
echo "[3/6] 安装 systemd 服务文件..."
cp "$SERVICE_FILE" "$SYSTEMD_DIR/$SERVICE_FILE"
chmod 644 "$SYSTEMD_DIR/$SERVICE_FILE"

# ── Step 4: 创建环境变量文件 ──
echo "[4/6] 创建环境变量文件..."
if [ ! -f /etc/stockstream/.env ]; then
    mkdir -p /etc/stockstream
    cat > /etc/stockstream/.env << 'EOF'
# StockStream V3.0 环境变量
STOCKSTREAM_HOST=0.0.0.0
STOCKSTREAM_PORT=8080
STOCKSTREAM_LOG_LEVEL=info
STOCKSTREAM_JETSON_MODE=1
STOCKSTREAM_MARKET__POLL_SECONDS=5
STOCKSTREAM_TTS__VOICE=zh_CN-huayan-medium
STOCKSTREAM_DATABASE__URL=sqlite+aiosqlite:///data/stockstream.db
DEEPSEEK_API_KEY=
RTMP_URL=
EOF
    chmod 600 /etc/stockstream/.env
    echo "  -> 已创建 /etc/stockstream/.env (请填入 DEEPSEEK_API_KEY 等配置)"
fi

# ── Step 5: 重新加载 systemd ──
echo "[5/6] 重新加载 systemd..."
systemctl daemon-reload

# ── Step 6: 启用开机自启动 ──
echo "[6/6] 启用开机自启动..."
systemctl enable ai-live.service

echo ""
echo "=== 安装完成 ==="
echo ""
echo "常用命令:"
echo "  启动服务:   sudo systemctl start ai-live"
echo "  停止服务:   sudo systemctl stop ai-live"
echo "  查看状态:   sudo systemctl status ai-live"
echo "  查看日志:   sudo journalctl -u ai-live -f"
echo "  重启服务:   sudo systemctl restart ai-live"
echo "  禁用自启:   sudo systemctl disable ai-live"
echo ""
echo "首次启动前，请确保:"
echo "  1. 项目已部署到 $INSTALL_DIR"
echo "  2. 虚拟环境已创建: $INSTALL_DIR/.venv"
echo "  3. 已编辑 /etc/stockstream/.env (DEEPSEEK_API_KEY)"
echo "  4. 模型已下载: python scripts/download_models.py --tts --face"
