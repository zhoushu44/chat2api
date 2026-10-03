#!/bin/bash
set -u
echo "=== 重启 chatgpt2api-13 容器（supervisor 按配置拉起全部服务） ==="
docker restart chatgpt2api-13
sleep 25
echo "=== 容器状态 ==="
docker ps --filter name=chatgpt2api-13 --format '{{.Status}}'
echo ""
echo "=== 进程（uvicorn + Go） ==="
docker exec chatgpt2api-13 sh -c "ps aux | grep -E '[u]vicorn|chatgpt2api-go' | head -5"
echo ""
echo "=== regiforge API 健康 ==="
docker exec chatgpt2api-13 sh -c "curl -s --max-time 8 http://127.0.0.1:8787/api/meta | head -c 150"
echo ""
echo "=== Go :3077 健康 ==="
curl -s --max-time 8 "http://127.0.0.1:3077/v1/models" | head -c 150
echo ""
echo "=== 代码版本确认（新 md5） ==="
docker exec chatgpt2api-13 md5sum /opt/regiforge/proxy/socks5/provider.py
md5sum /tmp/deploy/provider.py
