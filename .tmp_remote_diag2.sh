#!/bin/bash
# 第二轮诊断：任务统计 + 代理出口健康 + 资源
set -u

echo "===== A. 当前注册任务状态 ====="
curl -s --max-time 10 "http://127.0.0.1:3077/api/tasks" | python3 -m json.tool 2>/dev/null | head -60
echo ""
echo "===== B. 任务 1ac00da4c402 详情 ====="
curl -s --max-time 10 "http://127.0.0.1:3077/api/tasks/1ac00da4c402" | python3 -m json.tool 2>/dev/null | head -50
echo ""
echo "===== C. CPU 核数 ====="
nproc
echo ""
echo "===== D. chatgpt2api-13 容器资源使用 ====="
docker stats --no-stream chatgpt2api-13 regiforge 2>/dev/null
echo ""
echo "===== E. chatgpt2api-13 的挂载与配置位置 ====="
docker inspect chatgpt2api-13 --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}' 2>/dev/null
echo ""
echo "===== F. 容器内运行进程（浏览器实例数） ====="
docker exec chatgpt2api-13 ps aux 2>/dev/null | grep -E "chrome|chromium" | grep -v grep | wc -l
docker exec chatgpt2api-13 ps aux 2>/dev/null | head -10
