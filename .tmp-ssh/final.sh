#!/bin/bash
export SSHPASS='6Qz6ao0T1zvL'
sshpass -e ssh -o StrictHostKeyChecking=no root@192.6.121.16 bash -s <<'EOF'
docker exec -i chatgpt2api-12 python - <<'PY'
import json, urllib.request
tid = "d710b0a501aa"
def get(u):
    return json.load(urllib.request.urlopen("http://127.0.0.1:8787" + u, timeout=30))
s = get("/api/tasks/" + tid)
l = get("/api/tasks/" + tid + "/logs")["lines"]
print("== 终态:", json.dumps({k: s[k] for k in ("state", "done", "ok", "failed", "total")}, ensure_ascii=False))
for line in l:
    if any(x in line for x in ("V8", "成功 key", "失败", "完成，收口", "注册收口", "完成，成功")):
        print(line)
PY
echo "=== 内存 ==="; free -m | head -2
echo "=== 容器内存 ==="; docker stats --no-stream --format '{{.Name}}\tMEM={{.MemUsage}}' | grep chatgpt2api-12
EOF
