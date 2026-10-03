#!/bin/bash
set -u
echo "=== 原版 _http_engine.py 超时值分布 ==="
docker exec regiforge grep -n "timeout" /app/projects/chatgpt_register/steps/_http_engine.py | grep -E "=[0-9]+" | head -20
echo ""
echo "=== 原版 _sentinel.py goto/timeout ==="
docker exec regiforge grep -n "timeout" /app/projects/chatgpt_register/steps/_sentinel.py | grep -E "=[0-9_]+" | head -12
echo ""
echo "=== 原版 step01 goto timeout ==="
docker exec regiforge grep -n "timeout=" /app/projects/chatgpt_register/steps/step01_open_login.py | head -6
