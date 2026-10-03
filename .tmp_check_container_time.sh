#!/bin/bash
set -u
echo "=== 容器启动时间/创建时间 ==="
docker inspect chatgpt2api-13 --format 'started={{.State.StartedAt}} created={{.Created}}'
echo ""
echo "=== 容器内 wary provider md5（现在） ==="
docker exec chatgpt2api-13 md5sum /opt/regiforge/proxy/wary/provider.py /opt/regiforge/proxy/socks5/provider.py
echo ""
echo "=== watchtower 最近动作 ==="
docker logs watchtower --tail 15 2>&1 | head -18
