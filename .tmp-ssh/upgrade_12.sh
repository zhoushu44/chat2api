#!/bin/bash
export SSHPASS='6Qz6ao0T1zvL'
sshpass -e ssh -o StrictHostKeyChecking=no root@192.6.121.16 bash -s <<'EOF'
set -e
cd /root/chat2api/deploy/single
cp docker-compose.single.yml docker-compose.single.yml.bak-$(date +%Y%m%d-%H%M%S)
sed -i 's/chat2api:11.0/chat2api:12.0/; s/chatgpt2api-11/chatgpt2api-12/' docker-compose.single.yml
grep -q 'CHATGPT_SENTINEL_MODE' docker-compose.single.yml || sed -i 's/- CHATGPT2API_PROXY=/- CHATGPT_SENTINEL_MODE=auto\n      - CHATGPT2API_PROXY=/' docker-compose.single.yml
grep -E 'image:|container_name|SENTINEL' docker-compose.single.yml
docker compose -f docker-compose.single.yml pull 2>&1 | tail -2
docker compose -f docker-compose.single.yml up -d --remove-orphans 2>&1 | tail -3
sleep 8
docker ps --filter name=chatgpt2api --format '{{.Names}}\t{{.Image}}\t{{.Status}}'
docker ps -aq --filter name=chatgpt2api-11 | xargs -r docker rm -f
EOF
