#!/bin/bash
# 第二十四轮（决定性）：统计 100 个 warp 实例的 usque 引擎健康度
set -u

echo "===== A. 每个实例 engine.log 最后一次『Connected to MASQUE server』距今多久 ====="
NOW=$(date +%s)
STUCK=0
ALIVE=0
NOLOG=0
for d in /root/warp-instances/warp-*/; do
  name=$(basename "$d")
  # 最后一次 Connected 的时间
  last_conn=$(grep -a "Connected to MASQUE server" "$d/engine.log" 2>/dev/null | tail -1 | awk '{print $1, $2}')
  if [ -z "$last_conn" ]; then
    NOLOG=$((NOLOG+1))
    continue
  fi
  # 转 epoch
  ts=$(date -d "$last_conn" +%s 2>/dev/null)
  if [ -z "$ts" ]; then continue; fi
  age=$(( NOW - ts ))
  if [ $age -gt 600 ]; then
    STUCK=$((STUCK+1))
    echo "STUCK: $name last_connected ${age}s ago"
  else
    ALIVE=$((ALIVE+1))
  fi
done
echo ""
echo "===== 统计: 存活(10分钟内重连过)=$ALIVE | 疑似卡死(>10分钟)=$STUCK | 无日志=$NOLOG ====="
