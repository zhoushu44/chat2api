#!/bin/bash
set -u
echo "=== 从 chatgpt2api-13 容器日志找旧任务创建参数 ==="
docker logs chatgpt2api-13 2>&1 | grep -E "开始运行 captcha=" | tail -3
echo ""
echo "=== 尝试创建（补齐 provider 字段） ==="
TASK=$(curl -s --max-time 15 -X POST "http://127.0.0.1:8787/api/tasks" -H "Content-Type: application/json" -d '{
  "project_id": "chatgpt_register",
  "total": 3,
  "concurrency": 1,
  "headless": true,
  "captcha_id": "turnstile.captcharun",
  "email_id": "mailnest",
  "proxy_id": "socks5",
  "export_id": "chatgpt2api"
}')
echo "$TASK" | head -c 400
echo ""
TASK_ID=$(echo "$TASK" | grep -oE '"task_id":"[a-f0-9]+"' | cut -d'"' -f4)
echo "task_id: $TASK_ID"
echo "$TASK_ID" > /tmp/test_task_id.txt
