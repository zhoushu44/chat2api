#!/bin/bash
set -u
echo "=== 容器内 wary provider md5 ==="
docker exec chatgpt2api-13 md5sum /opt/regiforge/proxy/wary/provider.py
echo "=== 容器内 wary provider 的 prefer_whitelist 逻辑 ==="
docker exec chatgpt2api-13 grep -n "prefer_whitelist" /opt/regiforge/proxy/wary/provider.py | head -10
echo ""
echo "=== 容器内 uvicorn 进程的启动时间 vs 文件修改时间 ==="
docker exec chatgpt2api-13 sh -c "stat -c '%y %n' /opt/regiforge/proxy/wary/provider.py"
docker exec chatgpt2api-13 sh -c "ps -o lstart= -p \$(ps aux | grep '[u]vicorn web.app:app --host 127.0.0.1' | grep -v xvfb | awk '{print \$2}')"
