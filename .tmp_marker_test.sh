#!/bin/bash
set -u
docker cp /tmp/provider_wary_marker.py chatgpt2api-13:/opt/regiforge/proxy/wary/provider.py
docker exec chatgpt2api-13 md5sum /opt/regiforge/proxy/wary/provider.py
docker restart chatgpt2api-13
sleep 22
echo "=== 起标记测试任务 ==="
TASK=$(curl -s --max-time 15 -X POST "http://127.0.0.1:8787/api/tasks" -H "Content-Type: application/json" -d '{
  "project_id": "chatgpt_register",
  "total": 1,
  "concurrency": 1,
  "headless": true,
  "captcha_id": "turnstile.browser_manual",
  "email_id": "mailnest",
  "proxy_id": "wary",
  "export_id": "chatgpt2api"
}')
TASK_ID=$(echo "$TASK" | grep -oE '"task_id":"[a-f0-9]+"' | cut -d'"' -f4)
echo "task_id: $TASK_ID"
echo "$TASK_ID" > /tmp/marker_task_id.txt
sleep 25
echo "=== 任务日志（看是否 MARKER） ==="
curl -s --max-time 8 "http://127.0.0.1:8787/api/tasks/$TASK_ID/logs" | head -c 1200
echo ""
