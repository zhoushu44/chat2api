#!/bin/bash
# 用法: run_test.sh concurrency
export SSHPASS='6Qz6ao0T1zvL'
C=${1:-10}
sshpass -e ssh -o StrictHostKeyChecking=no root@192.6.121.16 bash -s <<EOF
docker exec -i chatgpt2api-12 python - <<'PY'
import json, urllib.request
body = {"project_id": "chatgpt_register", "captcha_id": "turnstile.browser_manual",
        "email_id": "mailnest", "proxy_id": "wary", "sms_id": "",
        "total": $C, "start": 1, "concurrency": $C, "stagger": 0, "headless": False}
req = urllib.request.Request("http://127.0.0.1:8787/api/tasks", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
r = json.load(urllib.request.urlopen(req, timeout=30))
print("TASK", r["task_id"])
PY
EOF
