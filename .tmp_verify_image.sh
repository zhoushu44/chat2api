#!/bin/bash
set -u
echo "=== A. 验证 10.0 镜像内含引擎自愈代码 ==="
docker run --rm --entrypoint sh zhoushu1/warp-pool:10.0 -c "
grep -c 'restartInstanceEngine' /app/server.js && echo 'FOUND: restartInstanceEngine'
grep -c 'failure_type' /app/server.js && echo 'FOUND: failure_type'
grep -c 'conn_fail_count' /app/server.js && echo 'FOUND: conn_fail_count'
node --check /app/server.js && echo 'SYNTAX OK'
"
echo ""
echo "=== B. 对比：当前运行容器（旧镜像）是否含这些 ==="
docker exec warp sh -c "grep -c 'restartInstanceEngine' /app/server.js" 2>/dev/null || echo "0 (旧版无此函数)"
