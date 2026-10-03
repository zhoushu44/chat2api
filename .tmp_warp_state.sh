#!/bin/bash
set -u
echo "=== 1. warp 容器当前镜像与挂载 ==="
docker inspect warp --format 'image={{.Config.Image}}'
docker inspect warp --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}
{{end}}'
echo "=== 2. 容器内 server.js 与宿主机 /root/warp/server.js md5 ==="
md5sum /root/warp/server.js
docker exec warp md5sum /app/server.js
echo "=== 3. 本地 compose 文件 ==="
ls -la /root/warp/docker-compose.yml 2>/dev/null && cat /root/warp/docker-compose.yml 2>/dev/null
echo "=== 4. 当前运行版本标识 ==="
docker exec warp sh -c "grep -m1 -n 'restartInstanceEngine' /app/server.js" 2>/dev/null && echo "HAVE_ENGINE_FIX" || echo "NO_ENGINE_FIX"
