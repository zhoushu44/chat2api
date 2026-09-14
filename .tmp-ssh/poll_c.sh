#!/bin/bash
# 用法: poll_c.sh task_id
export SSHPASS='6Qz6ao0T1zvL'
TID=$1
sshpass -e ssh -o StrictHostKeyChecking=no root@192.6.121.16 bash -s <<EOF
docker exec -i chatgpt2api-12 python - <<'PY'
import json, urllib.request, time
tid = "$TID"
def get(u):
    return json.load(urllib.request.urlopen("http://127.0.0.1:8787" + u, timeout=30))
seen = 0
for i in range(40):
    s = get("/api/tasks/" + tid)
    l = get("/api/tasks/" + tid + "/logs")["lines"]
    for line in l[seen:]:
        if any(x in line for x in ("[Sentinel V8]", "回退浏览器", "收口完成", "成功 key", "失败 status", "累计失败", "完成，成功")):
            print(line.strip(), flush=True)
    seen = len(l)
    print("---- 状态:", json.dumps({k: s[k] for k in ("state", "done", "ok", "failed", "total")}, ensure_ascii=False), flush=True)
    if s["state"] in ("done", "failed"):
        break
    time.sleep(25)
PY
free -m | sed -n 2p
docker stats --no-stream --format '{{.Name}}\tCPU={{.CPUPerc}}\tMEM={{.MemUsage}}' | grep chatgpt2api-12
EOF
