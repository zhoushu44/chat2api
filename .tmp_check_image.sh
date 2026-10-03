#!/bin/bash
set -u
echo "=== A. Docker Hub 上 warp-pool 的标签（看 10.0 是否已推送） ==="
curl -s --max-time 20 "https://hub.docker.com/v2/repositories/zhoushu1/warp-pool/tags?page_size=15" | tr ',' '\n' | grep -E '"name"|"last_updated"' | head -30

echo ""
echo "=== B. 当前是否有注册任务在跑 ==="
curl -s --max-time 8 "http://127.0.0.1:8787/api/tasks" | head -c 400
echo ""
echo "=== C. 当前池状态 ==="
curl -s --max-time 8 "http://195.72.185.32:4433/api/pool/status" | grep -oE '"total":[0-9]+|"available":[0-9]+|"in_use":[0-9]+|"unhealthy":[0-9]+' | head -4
