#!/bin/bash
export SSHPASS='6Qz6ao0T1zvL'
sshpass -e ssh -o StrictHostKeyChecking=no root@192.6.121.16 bash -s <<'EOF'
docker exec -i chatgpt2api-12 python - <<'PY'
import json, urllib.request
l = json.load(urllib.request.urlopen("http://127.0.0.1:8787/api/tasks/9fd39898a48b/logs", timeout=30))["lines"]
for line in l:
    if "[Sentinel V8]" in line or "回退浏览器" in line:
        print(line.strip())
PY
docker stats --no-stream --format '{{.Name}}\tCPU={{.CPUPerc}}\tMEM={{.MemUsage}}' | grep chatgpt2api-12
EOF
