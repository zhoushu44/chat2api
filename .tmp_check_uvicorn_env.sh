#!/bin/bash
set -u
echo "=== uvicorn 进程的 environ（env dump） ==="
PID=$(docker exec chatgpt2api-13 sh -c "ps aux | grep '[u]vicorn web.app:app --host 127.0.0.1' | grep -v xvfb | awk '{print \$2}' | head -1")
echo "uvicorn pid: $PID"
docker exec chatgpt2api-13 sh -c "tr '\0' '\n' < /proc/$PID/environ | grep -iE 'proxy|PROXY|REGIFORGE|http' | head -15"
echo ""
echo "=== uvicorn 打开的连接（4433 相关） ==="
docker exec chatgpt2api-13 sh -c "cat /proc/$PID/net/tcp 2>/dev/null | head -3; ss -tnp 2>/dev/null | grep $PID | head -10"
