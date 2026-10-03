#!/bin/bash
set -u
echo "=== 用 root 恢复原版 ==="
docker exec -u root regiforge sh -c "
cp /tmp/bak-20261002/_http_engine.py /app/projects/chatgpt_register/steps/_http_engine.py &&
cp /tmp/bak-20261002/_sentinel.py /app/projects/chatgpt_register/steps/_sentinel.py &&
cp /tmp/bak-20261002/step01_open_login.py /app/projects/chatgpt_register/steps/step01_open_login.py &&
cp /tmp/bak-20261002/wary_provider.py /app/proxy/wary/provider.py &&
cp /tmp/bak-20261002/socks5_provider.py /app/proxy/socks5/provider.py &&
echo RESTORE_REAL_OK
"
echo ""
echo "=== 确认签名（应有 set_password/bind_2fa） ==="
docker exec regiforge grep -n "def register_http" -A 14 /app/projects/chatgpt_register/steps/_http_engine.py | head -16
