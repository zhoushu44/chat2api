#!/bin/bash
set -u
echo "=== 用生产同款配置起测试任务（proxy=wary） ==="
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
echo "$TASK" | head -c 300
echo ""
TASK_ID=$(echo "$TASK" | grep -oE '"task_id":"[a-f0-9]+"' | cut -d'"' -f4)
echo "task_id: $TASK_ID"
echo "$TASK_ID" > /tmp/test_task_id.txt
