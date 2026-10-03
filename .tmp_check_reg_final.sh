#!/bin/bash
set -u
echo "=== 注册任务状态 ==="
curl -s --max-time 8 "http://127.0.0.1:8787/api/tasks" | head -c 260
echo ""
echo ""
echo "=== 自愈触发日志 ==="
docker logs warp --since 20m 2>&1 | grep -E "引擎已重启|故障释放|重启引擎|连接失败 x" | tail -8
echo "(空=未触发)"
echo ""
echo "=== 池状态 ==="
curl -s --max-time 10 "http://195.72.185.32:4433/api/pool/status" | grep -oE '"total":[0-9]+|"available":[0-9]+|"in_use":[0-9]+|"unhealthy":[0-9]+' | head -4
echo ""
echo "=== 端口监听数 ==="
ss -tln | grep -oE ':10[01][0-9][0-9]' | sort -u | wc -l
