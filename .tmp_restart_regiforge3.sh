#!/bin/bash
set -u
echo "=== 等旧进程（32）退出，确认只剩一个 uvicorn ==="
sleep 5
docker exec chatgpt2api-13 sh -c "ps aux | grep '[u]vicorn web.app:app' "
echo ""
echo "=== regiforge 健康 ==="
docker exec chatgpt2api-13 sh -c "curl -s --max-time 5 http://127.0.0.1:8787/api/tasks | head -c 300"
echo ""
