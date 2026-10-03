#!/bin/bash
set -u
echo "=== 1. warp 版本确认 ==="
docker inspect warp --format 'image={{.Config.Image}}'
docker images zhoushu1/warp-pool --format '{{.Repository}}:{{.Tag}} {{.ID}}' | head -3
docker exec warp sh -c "grep -c restartInstanceEngine /app/server.js"
echo "(上面数字 >0 = 引擎自愈代码已生效)"
echo ""
echo "=== 2. warp 本体 compose 文件版本注释（本地文件，非容器） ==="
grep -m1 "10.0\|8.0" /root/warp/docker-compose.yml
echo ""
echo "=== 3. 起真实注册测试（3 号，并发 1） ==="
TASK=$(curl -s --max-time 15 -X POST "http://127.0.0.1:8787/api/tasks" -H "Content-Type: application/json" -d '{
  "project_id": "chatgpt_register",
  "total": 3,
  "concurrency": 1,
  "headless": true,
  "captcha_id": "turnstile.browser_manual",
  "email_id": "mailnest",
  "proxy_id": "wary",
  "export_id": "chatgpt2api"
}')
TASK_ID=$(echo "$TASK" | grep -oE '"task_id":"[a-f0-9]+"' | cut -d'"' -f4)
echo "task_id: $TASK_ID"
