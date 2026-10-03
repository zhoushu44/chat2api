#!/bin/bash
# 远端诊断脚本：regiforge 注册慢/失败率高
set -u

echo "===== 1. 容器内 regiforge 数据目录结构 ====="
docker exec regiforge ls -la /app/data/ 2>/dev/null
echo ""
echo "===== 2. tasks 目录内容 ====="
docker exec regiforge ls -la /app/data/tasks/ 2>/dev/null
echo ""
echo "===== 3. debug/chatgpt_register 任务数量 ====="
docker exec regiforge ls /app/data/debug/chatgpt_register/ 2>/dev/null | wc -l
echo ""
echo "===== 4. 最近 15 个 debug 任务（按时间） ====="
docker exec regiforge ls -lt /app/data/debug/chatgpt_register/ 2>/dev/null | head -15
echo ""
echo "===== 5. regiforge 配置文件 ====="
docker exec regiforge find /app -maxdepth 3 -name "*.json" -not -path "*node_modules*" 2>/dev/null | head -20
echo ""
echo "===== 6. 最近 debug 任务的内容样本 ====="
LATEST=$(docker exec regiforge ls -t /app/data/debug/chatgpt_register/ 2>/dev/null | head -1)
echo "latest task: $LATEST"
docker exec regiforge ls -la "/app/data/debug/chatgpt_register/$LATEST" 2>/dev/null | head -30
echo ""
echo "===== 7. 容器内进程 ====="
docker exec regiforge ps aux 2>/dev/null | head -15
echo ""
echo "===== 8. chatgpt2api-13 (Go :3077) 容器日志尾部 ====="
docker logs chatgpt2api-13 --tail 60 2>&1 | head -80
echo ""
echo "===== 9. 系统 CPU/内存 ====="
docker exec regiforge cat /proc/loadavg 2>/dev/null
free -h | head -3
echo ""
echo "===== 10. regiforge 网络模式与端口 ====="
docker inspect regiforge --format '{{.HostConfig.NetworkMode}} | {{json .NetworkSettings.Networks}}' 2>/dev/null | head -c 600
echo ""
