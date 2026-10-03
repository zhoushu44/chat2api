#!/bin/bash
set -u
echo "=== regiforge 容器内 project.py 调用 register_http 的参数 ==="
docker exec regiforge grep -n "register_http(" -A 15 /app/projects/chatgpt_register/project.py | head -25
echo ""
echo "=== 容器内 _http_engine.py 的 register_http 签名 ==="
docker exec regiforge grep -n "def register_http" -A 20 /app/projects/chatgpt_register/steps/_http_engine.py | head -25
