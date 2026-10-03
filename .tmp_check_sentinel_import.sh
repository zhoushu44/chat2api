#!/bin/bash
set -u
echo "=== 原版 _http_engine.py 的 sentinel import ==="
docker exec regiforge grep -n "sentinel" /tmp/bak-20261002/_http_engine.py | grep -iE "import|from" | head -8
echo ""
echo "=== 原版 _sentinel_v8 在 regiforge 镜像里到底有没有 ==="
docker exec regiforge sh -c "ls -la /app/projects/chatgpt_register/steps/ | grep -E 'sentinel|_http'"
echo ""
echo "=== sentinel_vm 目录（V8 的 Node 沙箱） ==="
docker exec regiforge ls /app/projects/chatgpt_register/steps/sentinel_vm/ 2>/dev/null | head -5
