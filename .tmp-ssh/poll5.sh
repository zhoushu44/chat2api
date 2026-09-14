#!/bin/bash
export SSHPASS='6Qz6ao0T1zvL'
sshpass -e ssh -o StrictHostKeyChecking=no root@192.6.121.16 bash -s <<'EOF'
docker exec -i chatgpt2api-12 python - <<'PY'
import json, urllib.request, time
tid = "9fd39898a48b"
def get(u):
    return json.load(urllib.request.urlopen("http://127.0.0.1:8787" + u, timeout=30))
seen = 0
for i in range(30):
    s = get("/api/tasks/" + tid)
    l = get("/api/tasks/" + tid + "/logs")["lines"]
    for line in l[seen:]:
        if any(x in line for x in ("V8 成功", "V8 失败", "回退", "开始注册", "邮箱：", "收口完成", "成功 key", "失败", "完成，成功")):
            print(line)
    seen = len(l)
    print("---- 状态:", json.dumps({k: s[k] for k in ("state", "done", "ok", "failed", "total")}, ensure_ascii=False), flush=True)
    if s["state"] in ("done", "failed"):
        break
    time.sleep(30)
PY
echo "=== 内存 ==="; free -m | head -2
docker stats --no-stream --format '{{.Name}}\tMEM={{.MemUsage}}' | grep chatgpt2api-12
EOF
