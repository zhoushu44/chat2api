#!/bin/bash
set -u
echo "=== 池状态（json 手解析，无 python3） ==="
curl -s --max-time 8 "http://195.72.185.32:4433/api/pool/status" | grep -oE '"total":[0-9]+|"available":[0-9]+|"in_use":[0-9]+|"unhealthy":[0-9]+' | head -4
echo ""
echo "=== warp 日志最新（恢复完成了吗） ==="
docker logs warp --tail 5 2>&1 | head -6
