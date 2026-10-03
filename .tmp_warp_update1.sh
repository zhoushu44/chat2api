#!/bin/bash
set -u
echo "=== 1. 备份当前 warp 状态 ==="
mkdir -p /root/warp-backup-20261003
cp /root/warp/server.js /root/warp-backup-20261003/server.js.bak 2>/dev/null && echo "server.js backed up"
cp /root/warp/config.json /root/warp-backup-20261003/config.json.bak 2>/dev/null && echo "config.json backed up"
docker inspect warp > /root/warp-backup-20261003/container-inspect.json 2>/dev/null && echo "inspect backed up"
echo "current image:"
docker inspect warp --format '{{.Config.Image}} -> {{.Image}}'
echo ""
echo "=== 2. 拉取 10.0 镜像 ==="
docker pull zhoushu1/warp-pool:10.0 2>&1 | tail -5
echo ""
echo "=== 3. 确认拉到的镜像 ID 与 latest 是否一致 ==="
docker images zhoushu1/warp-pool --format '{{.Repository}}:{{.Tag}} {{.ID}} {{.CreatedSince}}' | head -6
