#!/bin/bash
set -u
echo "=== uvicorn 进程加载的 wary provider 模块路径 ==="
PID=$(docker exec chatgpt2api-13 sh -c "ps aux | grep '[u]vicorn web.app:app --host 127.0.0.1' | grep -v xvfb | awk '{print \$2}' | head -1")
echo "uvicorn pid: $PID"
docker exec chatgpt2api-13 sh -c "ls -la /proc/$PID/cwd/"
echo ""
echo "=== python -c 检查 sys.path 与模块来源（模拟 uvicorn 环境变量） ==="
docker exec chatgpt2api-13 sh -c "cat /proc/$PID/environ | tr '\0' '\n' | grep -E '^PWD|^PYTHON|^PATH' | head -5"
echo ""
echo "=== 文件系统里所有 wary/provider.py ==="
docker exec chatgpt2api-13 find / -name "provider.py" -path "*wary*" 2>/dev/null
echo ""
echo "=== pycache 残留 ==="
docker exec chatgpt2api-13 sh -c "find /opt/regiforge -name 'provider*.pyc' -path '*wary*' -o -name 'provider*.pyc' -path '*socks5*' 2>/dev/null | head -5"
