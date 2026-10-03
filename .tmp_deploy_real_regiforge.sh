#!/bin/bash
set -u
echo "=== 备份 regiforge 容器内原文件 ==="
docker exec regiforge sh -c "
mkdir -p /tmp/bak-20261002
cp /app/proxy/wary/provider.py /tmp/bak-20261002/wary_provider.py
cp /app/proxy/socks5/provider.py /tmp/bak-20261002/socks5_provider.py
cp /app/projects/chatgpt_register/steps/_sentinel_v8.py /tmp/bak-20261002/_sentinel_v8.py
cp /app/projects/chatgpt_register/steps/_http_engine.py /tmp/bak-20261002/_http_engine.py
cp /app/projects/chatgpt_register/steps/_sentinel.py /tmp/bak-20261002/_sentinel.py
cp /app/projects/chatgpt_register/steps/step01_open_login.py /tmp/bak-20261002/step01_open_login.py
echo BACKUP_OK
"
echo "=== 部署 A 组修复（先还原 wary 的 marker 版本为干净调试版） ==="
# 注意：/tmp/deploy/provider_wary.py 是带 traceback 的调试版（无 marker）
docker cp /tmp/deploy/provider_wary.py regiforge:/app/proxy/wary/provider.py
docker cp /tmp/deploy/provider.py regiforge:/app/proxy/socks5/provider.py
docker cp /tmp/deploy/_sentinel_v8.py regiforge:/app/projects/chatgpt_register/steps/_sentinel_v8.py
docker cp /tmp/deploy/_http_engine.py regiforge:/app/projects/chatgpt_register/steps/_http_engine.py
docker cp /tmp/deploy/_sentinel.py regiforge:/app/projects/chatgpt_register/steps/_sentinel.py
docker cp /tmp/deploy/step01_open_login.py regiforge:/app/projects/chatgpt_register/steps/step01_open_login.py
echo COPY_OK
echo "=== 语法检查 ==="
docker exec regiforge python3 -c "
import ast
for f in ['/app/proxy/wary/provider.py','/app/proxy/socks5/provider.py',
          '/app/projects/chatgpt_register/steps/_sentinel_v8.py',
          '/app/projects/chatgpt_register/steps/_http_engine.py',
          '/app/projects/chatgpt_register/steps/_sentinel.py',
          '/app/projects/chatgpt_register/steps/step01_open_login.py']:
    ast.parse(open(f, encoding='utf-8').read())
print('ALL_SYNTAX_OK')
"
docker exec regiforge sh -c "find /app -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null; true"
echo "=== 重启 regiforge 容器 ==="
docker restart regiforge
sleep 25
docker ps --filter name=regiforge --format '{{.Status}}'
echo ""
echo "=== 健康检查 ==="
curl -s --max-time 8 "http://127.0.0.1:8787/api/meta" | head -c 100
echo ""
