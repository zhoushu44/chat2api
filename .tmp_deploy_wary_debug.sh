#!/bin/bash
set -u
docker cp /tmp/deploy/provider_wary.py chatgpt2api-13:/opt/regiforge/proxy/wary/provider.py
docker exec chatgpt2api-13 python3 -c "import ast; ast.parse(open('/opt/regiforge/proxy/wary/provider.py', encoding='utf-8').read()); print('SYNTAX_OK')"
docker exec chatgpt2api-13 sh -c "find /opt/regiforge -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null; true"
# 重启 uvicorn（容器重启最稳）
docker restart chatgpt2api-13
sleep 25
docker exec chatgpt2api-13 sh -c "curl -s --max-time 8 http://127.0.0.1:8787/api/meta | head -c 80"
echo ""
echo "===起新测试任务==="
TASK=$(curl -s --max-time 15 -X POST "http://127.0.0.1:8787/api/tasks" -H "Content-Type: application/json" -d '{
  "project_id": "chatgpt_register",
  "total": 2,
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
