#!/bin/bash
# 第三轮诊断：日志统计失败原因分布 + 出口代理健康 + 出口切换逻辑
set -u

LOG="/tmp/c2a_logs.txt"
docker logs chatgpt2api-13 2>&1 | grep -E "^\[task:" > "$LOG" 2>/dev/null
echo "===== A. 任务日志总行数 ====="
wc -l "$LOG"

echo ""
echo "===== B. 失败相关关键行统计 ====="
echo "--- curl 超时 (60s) 次数 ---"
grep -c "Connection timed out after" "$LOG"
echo "--- ERR_TIMED_OUT / chrome-error 次数 ---"
grep -c "ERR_TIMED_OUT" "$LOG"
echo "--- 整段重试次数 ---"
grep -c "整段重试" "$LOG"
echo "--- 已切换出口 行数 ---"
grep -c "已切换出口" "$LOG"
echo "--- Sentinel 提取失败 ---"
grep -c "Sentinel 提取失败" "$LOG"
echo "--- 注册成功标志（导出/完成） ---"
grep -cE "注册成功|任务完成|导出成功|success" "$LOG"

echo ""
echo "===== C. 最近 3 小时内 各任务号出现的『切换出口』行样本 ====="
grep "已切换出口" "$LOG" | tail -30

echo ""
echo "===== D. 出口端口分布（从日志中提取 127.0.0.1:PORT） ====="
grep -oE "已切换出口: http://127.0.0.1:[0-9]+" "$LOG" | grep -oE "[0-9]+$" | sort | uniq -c | sort -rn | head -20

echo ""
echo "===== E. 最近 200 行任务日志尾部（看当前卡在哪一步） ====="
tail -60 "$LOG"
