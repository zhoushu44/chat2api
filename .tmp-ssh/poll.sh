#!/bin/bash
export SSHPASS='6Qz6ao0T1zvL'
sshpass -e ssh -o StrictHostKeyChecking=no root@192.6.121.16 bash -s <<'EOF'
docker exec -i chatgpt2api-12 python - <<'PY'
import json, urllib.request, time
tid = "d710b0a501aa"
def get(u):
    return json.load(urllib.request.urlopen("http://127.0.0.1:8787" + u, timeout=30))
for i in range(10):
    s = get("/api/tasks/" + tid)
    l = get("/api/tasks/" + tid + "/logs")
    print("== 状态:", json.dumps({k: s[k] for k in ("state", "done", "ok", "failed", "total")}, ensure_ascii=False))
    for line in l["lines"]:
        print(line)
    print()
    if s["state"] in ("done", "failed"):
        break
    time.sleep(30)
PY
EOF
