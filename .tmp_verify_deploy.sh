#!/bin/bash
set -u
echo "=== 部署后验证 md5 ==="
echo "--- 期望（本地源码） ---"
md5sum /tmp/deploy/provider_wary.py /tmp/deploy/provider.py /tmp/deploy/_sentinel_v8.py /tmp/deploy/_http_engine.py /tmp/deploy/_sentinel.py /tmp/deploy/step01_open_login.py 2>/dev/null | awk '{print $1, $2}'
echo "--- regiforge 容器内 ---"
docker exec regiforge md5sum /app/proxy/wary/provider.py /app/proxy/socks5/provider.py /app/projects/chatgpt_register/steps/_sentinel_v8.py /app/projects/chatgpt_register/steps/_http_engine.py /app/projects/chatgpt_register/steps/_sentinel.py /app/projects/chatgpt_register/steps/step01_open_login.py 2>&1
echo ""
echo "=== regiforge 容器内 steps 目录（确认文件名） ==="
docker exec regiforge ls /app/projects/chatgpt_register/steps/ 2>/dev/null | head -25
