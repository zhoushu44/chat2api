#!/bin/bash
set -u
echo "=== 负载 ==="
uptime
echo ""
echo "=== warp 容器 ==="
docker ps --filter name=warp --format '{{.Status}} | {{.Image}}'
echo ""
echo "=== 池状态 ==="
curl -s --max-time 10 "http://195.72.185.32:4433/api/pool/status" | grep -oE '"total":[0-9]+|"available":[0-9]+|"in_use":[0-9]+|"unhealthy":[0-9]+' | head -4
echo ""
echo "=== 恢复完成的实例数 ==="
docker logs warp --since 20m 2>&1 | grep -cE "复用启动完成"
echo ""
echo "=== 监听端口数 ==="
ss -tln | grep -cE ':10[01][0-9][0-9]'
echo ""
echo "=== 引擎/单盒进程数 ==="
echo "sing-box: $(ps aux | grep -c '[s]ing-box')"
echo "usque:    $(ps aux | grep -c '[u]sque')"
echo ""
echo "=== 最近日志 ==="
docker logs warp --tail 5 2>&1 | head -6
