#!/bin/bash
set -u
echo "=== 容器内语法检查（容器 node 版本与运行时一致） ==="
docker exec warp node --check /app/server.js && echo SYNTAX_OK
docker exec warp md5sum /app/server.js
echo ""
echo "=== 重启 warp 容器（管理端+实例都在里面，容器重启会恢复实例） ==="
docker restart warp
sleep 20
docker logs warp --tail 10 2>&1 | head -12
