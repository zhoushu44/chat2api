#!/bin/bash
set -u
cat > /tmp/show_fail.py << 'PYEOF'
import json, urllib.request
d = json.load(urllib.request.urlopen('http://127.0.0.1:8787/api/tasks/e0a2d7f3bbd5/logs', timeout=8))
lines = d.get('lines', [])
for l in lines:
    if '失败' in l or '成功' in l or 'ok=' in l or '已保存' in l or '[9/9]' in l or 'Key' in l:
        print(l[:220])
PYEOF
docker cp /tmp/show_fail.py regiforge:/tmp/show_fail.py
docker exec regiforge python3 /tmp/show_fail.py
