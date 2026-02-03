#!/bin/bash
# 使用 caffeinate 啟動交易程序，防止 Mac 睡眠導致 WebSocket 斷線
# 創建日期: 2026-02-03
# 用途: 解決 Power Nap 導致的網路連線中斷問題

set -e

# 顏色輸出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 專案根目錄
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo -e "${GREEN}======================================"
echo "交易程序啟動腳本 (含防睡眠)"
echo "======================================${NC}"
echo ""

# 檢查虛擬環境
if [ ! -d "$PROJECT_DIR/.venv" ]; then
    echo -e "${RED}錯誤: 找不到虛擬環境 .venv${NC}"
    echo "請先執行: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# 檢查配置檔案
CONFIG_FILE="$PROJECT_DIR/config/settings.yaml"
if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${RED}錯誤: 找不到配置檔案 $CONFIG_FILE${NC}"
    exit 1
fi

# 檢查 .env
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo -e "${YELLOW}警告: 找不到 .env 檔案${NC}"
    read -p "是否繼續？ (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# 顯示當前電源設定
echo -e "${YELLOW}當前系統電源設定:${NC}"
pmset -g | grep -E "sleep|Sleep|powernap" || true
echo ""

# 確認啟動
echo -e "${YELLOW}即將啟動交易程序...${NC}"
echo "  - 模式: live"
echo "  - 配置: $CONFIG_FILE"
echo "  - 防睡眠: 啟用 (caffeinate)"
echo ""
read -p "確認啟動？ (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "已取消"
    exit 0
fi

# 進入專案目錄
cd "$PROJECT_DIR"

# 啟動虛擬環境並執行
echo -e "${GREEN}正在啟動程序...${NC}"
echo "按 Ctrl+C 停止程序"
echo ""

# 設定 PYTHONPATH 並啟動
export PYTHONPATH="$PROJECT_DIR/src"
source .venv/bin/activate

# 使用 caffeinate 防止睡眠
caffeinate -dimsu python3 src/hyperliquid/main.py \
  --mode live \
  --config config/settings.yaml \
  --run-loop

echo ""
echo -e "${GREEN}程序已停止${NC}"
