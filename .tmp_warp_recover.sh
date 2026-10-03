#!/bin/bash
set -u
echo "=== 1. 容器状态与启动日志 ==="
docker ps --filter name=warp --format '{{.Status}}'
docker logs warp --tail 8 2>&1 | head -10

echo ""
echo "=== 2. 等待实例恢复（100 个实例需要几分钟全量恢复） ==="
for i in 1 2 3 4 5 6; do
  sleep 30
  S=$(curl -s --max-time 8 "http://195.72.185.32:4433/api/pool/status" | grep -oE '"total":[0-9]+|"available":[0-9]+|"unhealthy":[0-9]+' | tr '\n' ' ')
  echo "[$((i*30))s] $S"
done
