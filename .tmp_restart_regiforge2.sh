#!/bin/bash
set -u
echo "=== 重启 regiforge uvicorn（supervisor 会自动拉起） ==="
PID=$(docker exec chatgpt2api-13 sh -c "ps aux | grep '[u]vicorn web.app' | awk '{print \$2}' | head -1")
echo "old uvicorn pid: $PID"
[ -n "$PID" ] && docker exec chatgpt2api-13 kill "$PID"
sleep 5
echo "=== 新进程 ==="
docker exec chatgpt2api-13 sh -c "ps aux | grep '[u]vicorn web.app' | head -3"
echo "=== regiforge 健康 ==="
sleep 3
docker exec chatgpt2api-13 sh -c "curl -s --max-time 5 http://127.0.0.1:8787/api/meta | head -c 200"
echo ""
