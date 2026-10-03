#!/bin/bash
# 第二十一轮：核心对比——实例 66 (10076 死) vs 实例 0 (10010 活) 的 singbox.json 差异
set -u

echo "===== A. warp-66 singbox.json ====="
python3 -m json.tool /root/warp-instances/warp-66/singbox.json 2>/dev/null | head -50
echo ""
echo "===== B. warp-0 singbox.json（对照） ====="
python3 -m json.tool /root/warp-instances/warp-0/singbox.json 2>/dev/null | head -50

echo ""
echo "===== C. warp-66 usque 引擎日志尾部 ====="
tail -20 /root/warp-instances/warp-66/engine.log 2>/dev/null

echo ""
echo "===== D. warp-66 sing-box 进程状态 ====="
PORT66=$((10076))
# 从 ss 找 10076 的 PID
PID66=$(ss -tlnp | grep ":$PORT66 " | grep -oE "pid=[0-9]+" | head -1 | cut -d= -f2)
echo "sing-box PID for port 10076: $PID66"
[ -n "$PID66" ] && ps -o pid,stat,rss,etime,cmd -p "$PID66" 2>/dev/null

echo ""
echo "===== E. warp-66 引擎（usque 20066）是否监听 ====="
ENGINE_PORT=$((20000 + 66))
ss -tlnp | grep ":$ENGINE_PORT " || echo "engine port $ENGINE_PORT NOT LISTENING"
echo "--- meta.json ---"
cat /root/warp-instances/warp-66/meta.json 2>/dev/null | head -c 600; echo ""
