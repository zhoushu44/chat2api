#!/bin/bash
set -u
cat > /tmp/show_logs.py << 'PYEOF'
import json, urllib.request
d = json.load(urllib.request.urlopen('http://127.0.0.1:8787/api/tasks/e0a2d7f3bbd5/logs', timeout=8))
lines = d.get('lines', [])
for l in lines[30:]:
    print(l)
PYEOF
python3 /tmp/show_logs.py | head -55
