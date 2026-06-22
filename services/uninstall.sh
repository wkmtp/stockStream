#!/bin/bash
# StockStream systemd 卸载脚本
set -e

if [ "$EUID" -ne 0 ]; then
    echo "错误: 请使用 sudo 运行此脚本"
    exit 1
fi

echo "=== StockStream systemd 卸载 ==="

systemctl stop ai-live.service 2>/dev/null || true
systemctl disable ai-live.service 2>/dev/null || true
rm -f /etc/systemd/system/ai-live.service
systemctl daemon-reload

echo "已卸载 ai-live.service"
