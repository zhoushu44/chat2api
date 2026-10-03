#!/bin/bash
set -u
echo "=== supervisor 状态 ==="
docker exec chatgpt2api-13 supervisorctl status 2>&1 | head -5
echo ""
echo "=== supervisor 日志（最近） ==="
docker exec chatgpt2api-13 sh -c "tail -20 /var/log/supervisor/*.log 2>/dev/null | tail -25"
echo ""
echo "=== 重启 regiforge program ==="
docker exec chatgpt2api-13 supervisorctl restart regiforge 2>&1
sleep 8
docker exec chatgpt2api-13 supervisorctl status 2>&1
echo ""
docker exec chatgpt2api-13 sh -c "curl -s --max-time 5 http://127.0.0.1:8787/api/meta | head -c 150"
echo ""
