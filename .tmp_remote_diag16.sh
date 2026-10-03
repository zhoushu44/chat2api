#!/bin/bash
# 第十六轮：warp 池 sid 会话机制深挖 + 资源压力
set -u

echo "===== A. warp 容器内进程数与内存 ====="
docker exec warp sh -c "ls /proc | grep -E '^[0-9]+$' | wc -l" 2>/dev/null
docker stats --no-stream warp 2>/dev/null
echo ""
echo "===== B. warp 容器 cgroup 内存 ====="
docker exec warp sh -c "cat /sys/fs/cgroup/memory.current 2>/dev/null || cat /sys/fs/cgroup/memory/memory.usage_in_bytes 2>/dev/null" 2>/dev/null
docker exec warp sh -c "cat /sys/fs/cgroup/memory.max 2>/dev/null || cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null" 2>/dev/null

echo ""
echo "===== C. 服务器 sing-box 进程总数 ====="
ps aux | grep -c "[s]ing-box"
echo "--- 内存 TOP10 ---"
ps aux --sort=-%mem | head -11

echo ""
echo "===== D. sid 会话端口分配规律（连续取 6 个 sid 看端口增量） ====="
for i in 1 2 3 4 5 6; do
  R=$(curl -s --max-time 10 "http://195.72.185.32:4433/api/proxies?num=1&type=json&format=n&sid=chatgpt-probe-$i&time=20")
  P=$(echo "$R" | grep -oE '"proxy":"socks5://195\.72\.185\.32:[0-9]+' | grep -oE '[0-9]+$')
  S=$(echo "$R" | grep -oE '"status":"[a-z_]+"' | head -1)
  echo "sid-$i -> port $P $S"
done

echo ""
echo "===== E. warp 容器日志：sid 会话创建相关（最近 10 分钟） ====="
docker logs warp --since 10m 2>&1 | grep -iE "session|sticky|sid|allocat|create" | tail -15

echo ""
echo "===== F. 释放刚才的测试 sid 会话 ====="
for i in 1 2 3 4 5 6; do
  curl -s --max-time 5 -X POST "http://195.72.185.32:4433/api/pool/release" -H "Content-Type: application/json" -d "{\"session_id\":\"chatgpt-probe-$i\"}" | head -c 100; echo ""
done
