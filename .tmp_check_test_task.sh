#!/bin/bash
set -u
echo "=== 测试任务日志 ==="
curl -s --max-time 10 "http://127.0.0.1:8787/api/tasks/0c1989063412/logs" | python3 -c "
import json, sys
logs = json.load(sys.stdin)
if isinstance(logs, list):
    for line in logs[-50:]:
        print(line if isinstance(line, str) else json.dumps(line, ensure_ascii=False))
else:
    print(logs)
" 2>/dev/null || curl -s --max-time 10 "http://127.0.0.1:8787/api/tasks/0c1989063412/logs" | head -c 3000
