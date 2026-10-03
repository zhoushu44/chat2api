#!/bin/bash
set -u
echo "=== 1. 查看可用的实例管理 API ==="
curl -s --max-time 10 "http://195.72.185.32:4433/api/containers" | head -c 600
echo ""
echo ""
echo "=== 2. 查 API 路由（从 server.js 提取） ==="
docker exec warp sh -c "grep -oE \"app\.(get|post|delete)\('/api/[a-z/_:.-]+'\" /app/server.js | sort -u | head -30"
