#!/bin/bash
# StockStream systemd 安装脚本
# 使用方法: sudo bash install.sh

set -e

echo "=== StockStream systemd 安装 ==="

# 检查是否为 root
if [ "$EUID" -ne 0 ]; then
    echo "错误: 请使用 sudo 运行此脚本"
    exit 1
fi

SERVICE_FILE="ai-live.service"
INSTALL_DIR="/opt/stockstream"
SYSTEMD_DIR="/etc/systemd/system"

echo "[1/5] 创建安装目录..."
mkdir -p "$INSTALL_DIR"/{data,logs,cache,config}
chown -R stockstream:stockstream "$INSTALL_DIR"

echo "[2/5] 复制服务文件..."
cp "$SERVICE_FILE" "$SYSTEMD_DIR/$SERVICE_FILE"
chmod 644 "$SYSTEMD_DIR/$SERVICE_FILE"

echo "[3/5] 创建环境变量文件..."
if [ ! -f /etc/stockstream/.env ]; then
    mkdir -p /etc/stockstream
    cat > /etc/stockstream/.env << 'EOF'
# StockStream 环境变量
STOCKSTREAM_HOST=0.0.0.0
STOCKSTREAM_PORT=8000
STOCKSTREAM_LOG_LEVEL=info
STOCKSTREAM_MARKET__POLL_SECONDS=5
STOCKSTREAM_TTS__VOICE=zh_CN-huayan-medium
STOCKSTREAM_DATABASE__URL=sqlite+aiosqlite:///data/stockstream.db
EOF
    chmod 600 /etc/stockstream/.env
    echo "  -> 已创建 /etc/stockstream/.env (请修改API密钥等敏感配置)"
fi

echo "[4/5] 重新加载 systemd..."
systemctl daemon-reload

echo "[5/5] 启用开机自启动..."
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
echo "  1. 已安装 Docker 和 docker-compose"
echo "  2. 已配置 /etc/stockstream/.env"
echo "  3. 项目文件已复制到 $INSTALL_DIR"
