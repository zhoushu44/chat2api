#!/bin/bash
set -u
echo "=== 1. 恢复进度（重启后时间 vs 实例数） ==="
docker logs warp --since 8m 2>&1 | grep -cE "复用启动完成"
echo "已完成恢复的实例数（上面数字）"
echo ""
echo "=== 2. 最近的 RECOVERY / ENGINE 日志 ==="
docker logs warp --since 5m 2>&1 | grep -E "RECOVERY|ENGINE" | tail -12
echo ""
echo "=== 3. 错误/告警日志 ==="
docker logs warp --since 8m 2>&1 | grep -iE "ERROR|WARN|失败|超时" | tail -12
echo ""
echo "=== 4. 当前实例进程数 ==="
ps aux | grep -c "[s]ing-box"
ps aux | grep -c "[u]sque"
echo ""
echo "=== 5. 容器资源 ==="
docker stats --no-stream warp 2>/dev/null
free -h | head -2
