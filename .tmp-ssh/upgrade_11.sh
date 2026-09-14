#!/bin/bash
export SSHPASS='6Qz6ao0T1zvL'
sshpass -e ssh -o StrictHostKeyChecking=no -p 22 root@192.6.121.16 bash -s <<'EOF'
set -e
cd /root/chat2api/deploy/single
cp docker-compose.single.yml docker-compose.single.yml.bak-$(date +%Y%m%d-%H%M%S)
sed -i 's/chat2api:10.0/chat2api:11.0/; s/chatgpt2api-10/chatgpt2api-11/' docker-compose.single.yml
grep -E 'container_name|image:' docker-compose.single.yml
docker compose -f docker-compose.single.yml pull 2>&1 | tail -2
docker compose -f docker-compose.single.yml up -d --remove-orphans 2>&1 | tail -3
sleep 8
docker ps --filter name=chatgpt2api --format '{{.Names}} {{.Image}} {{.Status}}'
docker ps -aq --filter name=chatgpt2api-10 | xargs -r docker rm -f
EOF
