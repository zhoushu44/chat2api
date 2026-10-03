#!/bin/bash
set -u
cd /root/warp

echo "=== 1. 同步 latest 标签到新镜像（compose 用 latest） ==="
docker pull zhoushu1/warp-pool:latest 2>&1 | tail -3
echo "latest 现在指向:"
docker images zhoushu1/warp-pool:latest --format '{{.ID}} ({{.CreatedSince}})'

echo ""
echo "=== 2. compose 重建容器 ==="
docker compose pull 2>&1 | tail -3
docker compose up -d 2>&1 | tail -5

echo ""
echo "=== 3. 等待启动 ==="
sleep 12
docker ps --filter name=warp --format '{{.Names}} {{.Status}} {{.Image}}'
echo ""
echo "=== 4. 验证容器内代码版本 ==="
docker exec warp sh -c "grep -c 'restartInstanceEngine' /app/server.js" 2>/dev/null && echo "ENGINE_FIX_PRESENT"
docker exec warp md5sum /app/server.js
