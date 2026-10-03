#!/bin/bash
set -u
echo "=== 任务日志后半段（账号1失败原因 + 账号2进展） ==="
curl -s --max-time 8 "http://127.0.0.1:8787/api/tasks/e0a2d7f3bbd5/logs" | python3 -c "
import json, sys
d = json.load(sys.stdin)
lines = d.get('lines', [])
for l in lines[30:]:
    print(l)
" 2>/dev/null | head -50
