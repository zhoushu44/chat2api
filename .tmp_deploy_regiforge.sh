#!/bin/bash
set -u
# 备份容器内原文件
echo "=== 备份 ==="
docker exec chatgpt2api-13 sh -c "
mkdir -p /tmp/regiforge-bak-20261002
cp /opt/regiforge/proxy/socks5/provider.py /tmp/regiforge-bak-20261002/provider.py
cp /opt/regiforge/projects/chatgpt_register/steps/_sentinel_v8.py /tmp/regiforge-bak-20261002/_sentinel_v8.py
cp /opt/regiforge/projects/chatgpt_register/steps/_http_engine.py /tmp/regiforge-bak-20261002/_http_engine.py
cp /opt/regiforge/projects/chatgpt_register/steps/_sentinel.py /tmp/regiforge-bak-20261002/_sentinel.py
cp /opt/regiforge/projects/chatgpt_register/steps/step01_open_login.py /tmp/regiforge-bak-20261002/step01_open_login.py
echo BACKUP_OK
"
# 复制进容器
echo "=== 复制新文件 ==="
docker cp /tmp/deploy/provider.py chatgpt2api-13:/opt/regiforge/proxy/socks5/provider.py
docker cp /tmp/deploy/_sentinel_v8.py chatgpt2api-13:/opt/regiforge/projects/chatgpt_register/steps/_sentinel_v8.py
docker cp /tmp/deploy/_http_engine.py chatgpt2api-13:/opt/regiforge/projects/chatgpt_register/steps/_http_engine.py
docker cp /tmp/deploy/_sentinel.py chatgpt2api-13:/opt/regiforge/projects/chatgpt_register/steps/_sentinel.py
docker cp /tmp/deploy/step01_open_login.py chatgpt2api-13:/opt/regiforge/projects/chatgpt_register/steps/step01_open_login.py
echo COPY_OK

# 语法检查 + 清 pycache
echo "=== 语法检查 ==="
docker exec chatgpt2api-13 python3 -c "
import ast
for f in ['/opt/regiforge/proxy/socks5/provider.py',
          '/opt/regiforge/projects/chatgpt_register/steps/_sentinel_v8.py',
          '/opt/regiforge/projects/chatgpt_register/steps/_http_engine.py',
          '/opt/regiforge/projects/chatgpt_register/steps/_sentinel.py',
          '/opt/regiforge/projects/chatgpt_register/steps/step01_open_login.py']:
    ast.parse(open(f, encoding='utf-8').read())
print('ALL SYNTAX OK')
"
docker exec chatgpt2api-13 sh -c "find /opt/regiforge -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null; echo PYCACHE_CLEARED"
