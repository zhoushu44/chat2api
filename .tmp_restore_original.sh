#!/bin/bash
set -u
echo "=== 1. 恢复原版（从容器内备份） ==="
docker exec regiforge sh -c "
cp /tmp/bak-20261002/_http_engine.py /app/projects/chatgpt_register/steps/_http_engine.py
cp /tmp/bak-20261002/_sentinel.py /app/projects/chatgpt_register/steps/_sentinel.py
cp /tmp/bak-20261002/step01_open_login.py /app/projects/chatgpt_register/steps/step01_open_login.py
cp /tmp/bak-20261002/wary_provider.py /app/proxy/wary/provider.py
cp /tmp/bak-20261002/socks5_provider.py /app/proxy/socks5/provider.py
echo RESTORE_OK
"
echo ""
echo "=== 2. 移除我加的 _sentinel_v8.py（原版不存在） ==="
docker exec regiforge sh -c "rm -f /app/projects/chatgpt_register/steps/_sentinel_v8.py; echo REMOVED"
docker exec regiforge sh -c "ls /app/projects/chatgpt_register/steps/ | grep -E 'sentinel|http' "
echo ""
echo "=== 3. 验证签名匹配（set_password 应该回来了） ==="
docker exec regiforge grep -n "def register_http" -A 12 /app/projects/chatgpt_register/steps/_http_engine.py | head -14
