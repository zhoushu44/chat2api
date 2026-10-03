#!/bin/bash
set -u
echo "=== warp 实例恢复进度 ==="
curl -s --max-time 8 "http://195.72.185.32:4433/api/pool/status" | python3 -c "
import json,sys
d=json.load(sys.stdin)
data=d.get('data',{})
print('total:', data.get('total'), 'available:', data.get('available'), 'in_use:', data.get('in_use'), 'unhealthy:', data.get('unhealthy'))
"
echo ""
echo "=== 再跑一个 3 号测试任务 ==="
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
echo "$TASK_ID" > /tmp/test_task_id.txt
