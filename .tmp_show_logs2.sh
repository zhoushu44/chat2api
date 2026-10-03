#!/bin/bash
set -u
cat > /tmp/show_logs.py << 'PYEOF'
import json, urllib.request
d = json.load(urllib.request.urlopen('http://127.0.0.1:8787/api/tasks/e0a2d7f3bbd5/logs', timeout=8))
lines = d.get('lines', [])
for l in lines[30:]:
    print(l)
PYEOF
docker cp /tmp/show_logs.py regiforge:/tmp/show_logs.py
docker exec regiforge python3 /tmp/show_logs.py 2>&1 | head -60
