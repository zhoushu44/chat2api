#!/bin/bash
set -u
echo "=== 杀旧 uvicorn（pid 32，跑的旧代码） ==="
docker exec chatgpt2api-13 sh -c "kill -9 32 2>/dev/null; echo KILLED"
sleep 5
echo "=== 剩余 uvicorn ==="
docker exec chatgpt2api-13 sh -c "ps aux | grep '[u]vicorn web.app:app'"
echo ""
echo "=== 8787 谁在听 ==="
docker exec chatgpt2api-13 sh -c "ss -tlnp 2>/dev/null | grep 8787 || netstat -tlnp 2>/dev/null | grep 8787"
echo ""
echo "=== regiforge API 健康 ==="
docker exec chatgpt2api-13 sh -c "curl -s --max-time 5 http://127.0.0.1:8787/api/meta | head -c 120"
echo ""
