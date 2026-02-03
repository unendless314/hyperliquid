#!/bin/bash
# 診斷腳本：檢測 Mac 睡眠模式對交易程序的影響
# 用法: ./diagnose_sleep_mode.sh

echo "======================================"
echo "Mac 睡眠模式診斷工具"
echo "======================================"
echo ""

echo "【1】系統電源設定"
echo "--------------------------------------"
pmset -g | grep -E "sleep|Sleep"
echo ""

echo "【2】Power Nap 狀態"
echo "--------------------------------------"
pmset -g | grep -i powernap
echo ""

echo "【3】當前防睡眠斷言"
echo "--------------------------------------"
pmset -g assertions | grep -E "PreventUserIdleSystemSleep|NoIdleSleepAssertion"
echo ""

echo "【4】最近的睡眠/喚醒事件"
echo "--------------------------------------"
pmset -g log | grep -E "(Sleep|Wake|DarkWake)" | tail -10
echo ""

echo "【5】WebSocket 配置"
echo "--------------------------------------"
echo "從程序代碼中檢測到的 WebSocket 心跳配置："
echo "  - ping_interval: 20 秒"
echo "  - ping_timeout: 10 秒"
echo ""

echo "【6】建議的驗證步驟"
echo "--------------------------------------"
echo "1. 關閉 Power Nap:"
echo "   sudo pmset -a powernap 0"
echo ""
echo "2. 使用 caffeinate 運行程序:"
echo "   caffeinate -dimsu python3 src/hyperliquid/main.py --mode live --config config/settings.yaml --run-loop"
echo ""
echo "3. 監控系統電源事件（在另一個終端）:"
echo "   pmset -g log | grep -E \"(Sleep|Wake)\" >> ~/power_events_\$(date +%Y%m%d).log"
echo ""

echo "======================================"
echo "診斷完成！"
echo "======================================"
