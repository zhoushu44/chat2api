#!/bin/bash
# 升级服务器容器到最新 10.0 镜像（含 stopCh 修复）
export SSHPASS='6Qz6ao0T1zvL'
HOST=root@192.6.121.16
sshpass -e ssh -o StrictHostKeyChecking=no -p 22 $HOST bash -s <<'EOF'
set -e
cd /root/chat2api/deploy/single
docker compose -f docker-compose.single.yml pull 2>&1 | tail -3
docker compose -f docker-compose.single.yml up -d 2>&1 | tail -3
sleep 5
docker ps --filter name=chatgpt2api-10 --format '{{.Names}} {{.Image}} {{.Status}}'
EOF
