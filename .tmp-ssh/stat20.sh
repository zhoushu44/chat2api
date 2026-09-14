#!/bin/bash
export SSHPASS='6Qz6ao0T1zvL'
sshpass -e ssh -o StrictHostKeyChecking=no root@192.6.121.16 bash -s <<'EOF'
docker exec -i chatgpt2api-12 python - <<'PY'
import json, urllib.request
tid = "bc70135251ac"
def get(u):
    return json.load(urllib.request.urlopen("http://127.0.0.1:8787" + u, timeout=30))
s = get("/api/tasks/" + tid)
l = get("/api/tasks/" + tid + "/logs")["lines"]
print("== 终态:", json.dumps({k: s[k] for k in ("state","done","ok","failed","total")}, ensure_ascii=False))
import re
ok = sum(1 for x in l if "成功 key" in x)
otp = sum(1 for x in l if "邮箱验证码获取失败" in x)
print("成功key行:", ok, "邮箱码失败行:", otp)
for x in l:
    if "成功 key" in x or "失败 status" in x and "邮箱验证码" in x:
        pass
# 打印最近 12 条关键事件
keys = [x.strip() for x in l if ("成功 key" in x) or ("失败 status" in x) or ("收口完成" in x) or ("完成，成功" in x)]
for x in keys[-14:]:
    print(x)
PY
free -m | sed -n 2p
docker stats --no-stream --format '{{.Name}}\tCPU={{.CPUPerc}}\tMEM={{.MemUsage}}' | grep chatgpt2api-12
EOF
