#!/bin/bash
set -u
echo "=== wary 测试任务日志 ==="
curl -s --max-time 10 "http://127.0.0.1:8787/api/tasks/e3ad2a4cf579/logs" | python3 -c "
import json, sys
d = json.load(sys.stdin)
for line in d.get('lines', []):
    print(line)
" 2>/dev/null | tail -45
