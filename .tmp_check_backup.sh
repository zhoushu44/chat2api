#!/bin/bash
set -u
echo "=== 备份文件里的签名 ==="
docker exec regiforge sh -c "
grep -n 'def register_http' -A 16 /tmp/bak-20261002/_http_engine.py 2>/dev/null | head -20
"
echo ""
echo "=== 原版 _sentinel_v8 备份是否存在 ==="
docker exec regiforge ls -la /tmp/bak-20261002/ 2>/dev/null
echo ""
echo "=== chatgpt2api-13 里的原版（更早的备份） ==="
docker exec chatgpt2api-13 sh -c "ls /tmp/regiforge-bak-20261002/ 2>/dev/null"
docker exec chatgpt2api-13 sh -c "grep -n 'def register_http' -A 16 /tmp/regiforge-bak-20261002/_http_engine.py 2>/dev/null | head -20"
