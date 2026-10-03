#!/bin/bash
set -u
echo "=== chatgpt2api-13 mounts ==="
docker inspect chatgpt2api-13 --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}
{{end}}'
echo "=== /root/chat2api/deploy/single/ ==="
ls -la /root/chat2api/deploy/single/ 2>/dev/null
echo "=== regiforge code path in container ==="
docker exec chatgpt2api-13 ls /opt/regiforge/ 2>/dev/null | head -5
docker exec chatgpt2api-13 md5sum /opt/regiforge/proxy/socks5/provider.py 2>/dev/null
echo "=== host regiforge source? ==="
ls -la /root/chat2api/ 2>/dev/null | head -15
find /root -maxdepth 3 -name "regiforge" -type d 2>/dev/null | grep -v warp-instances | head -5
