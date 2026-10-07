#!/bin/bash
set -e
TS=$(date +%Y%m%d%H%M%S)
echo "=== backup original binary ==="
docker cp chatgpt2api-13:/chatgpt2api-go /root/chatgpt2api-go.bak-$TS
ls -la /root/chatgpt2api-go.bak-$TS
echo "=== swap in new binary ==="
docker cp /tmp/chatgpt2api-go-new chatgpt2api-13:/chatgpt2api-go
docker exec chatgpt2api-13 chmod +x /chatgpt2api-go
echo "=== checksums ==="
echo -n "host new : "; sha256sum /tmp/chatgpt2api-go-new | awk '{print $1}'
echo -n "in ctr   : "; docker exec chatgpt2api-13 sha256sum /chatgpt2api-go | awk '{print $1}'
echo "=== restart container ==="
docker restart chatgpt2api-13
sleep 8
docker ps --filter name=chatgpt2api-13 --format '{{.Names}} | {{.Status}}'
