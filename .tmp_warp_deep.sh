#!/bin/bash
set -u
echo "=== 1. 端口 10015 是否监听 ==="
ss -tln | grep -E ':10015' || echo "10015 NOT LISTENING"
echo ""
echo "=== 2. 实际监听的 10010-10109 端口清单 ==="
ss -tln | grep -oE ':10[01][0-9][0-9]' | sort -u | head -20
echo "总数: $(ss -tln | grep -oE ':10[01][0-9][0-9]' | sort -u | wc -l)"
echo ""
echo "=== 3. warp-5 实例状态（10015） ==="
ls -la /root/warp-instances/warp-5/ 2>/dev/null
echo "--- meta.json ---"
cat /root/warp-instances/warp-5/meta.json 2>/dev/null
echo ""
echo "=== 4. warp-5 的 sing-box 进程是否活着 ==="
PID=$(cat /root/warp-instances/warp-5/meta.json 2>/dev/null | grep -oE '"pid":[0-9]+' | grep -oE '[0-9]+')
echo "meta pid: $PID"
[ -n "$PID" ] && ps -o pid,stat,etime,cmd -p "$PID" 2>/dev/null || echo "进程不存在"
echo ""
echo "=== 5. warp-5 singbox 日志尾部 ==="
tail -15 /root/warp-instances/warp-5/singbox.log 2>/dev/null
echo ""
echo "=== 6. 容器内进程数统计 ==="
docker exec warp sh -c "ls /proc | grep -cE '^[0-9]+$'"
echo ""
echo "=== 7. 最近的 ERROR ==="
docker logs warp --since 20m 2>&1 | grep -iE "ERROR|失败|FATAL" | tail -10
