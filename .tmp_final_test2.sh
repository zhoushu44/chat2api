#!/bin/bash
set -u
docker restart regiforge
sleep 22
echo "=== 容器状态 ==="
docker ps --filter name=regiforge --format '{{.Status}}'
echo "=== 健康 ==="
curl -s --max-time 8 "http://127.0.0.1:8787/api/meta" | head -c 80
echo ""
echo "=== 最终验证任务 5 号 ==="
TASK=$(curl -s --max-time 15 -X POST "http://127.0.0.1:8787/api/tasks" -H "Content-Type: application/json" -d '{
  "project_id": "chatgpt_register",
  "total": 5,
  "concurrency": 1,
  "headless": true,
  "captcha_id": "turnstile.browser_manual",
  "email_id": "mailnest",
  "proxy_id": "wary",
  "export_id": "chatgpt2api"
}')
TASK_ID=$(echo "$TASK" | grep -oE '"task_id":"[a-f0-9]+"' | cut -d'"' -f4)
echo "task_id: $TASK_ID"
echo "$TASK_ID" > /tmp/final_task_id.txt
