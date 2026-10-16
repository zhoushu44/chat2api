# -*- coding: utf-8 -*-
"""fix10 生图实测：当前时间 + 冷却状态 + 连发生图"""
import sys, time

sys.path.insert(0, r"e:\360MoveData\Users\Administrator\Desktop\chat2api")
from _s import run

AUTH = "zs1236547"

# 0. 当前时间 + 容器状态 + 冷却状态
o, e = run("date -u && docker ps --filter name=chatgpt2api --format '{{.Names}} | {{.Image}} | {{.Status}}'")
print("== env ==")
print(o.strip())

o, e = run("docker run --rm -v /root/chat2api/deploy/gray/data:/data python:3-alpine python3 -c "
           "\"import json,time;d=json.load(open('/data/accounts.json'));"
           "accs=list(d.values()) if isinstance(d,dict) and 'accounts' not in d else list(d.get('accounts',{}).values());"
           "now=int(time.time());"
           "cd=[a for a in accs if a.get('cooldown_until',0)>now];"
           "print('total:',len(accs),'cooldown_active:',len(cd))\"")
print("== cooldown ==", o.strip(), e[:200])

# 1. 连发 3 次生图
print("== IMAGE TEST x3 ==")
for i in range(3):
    t0 = time.time()
    o, e = run(
        "curl -s -m 180 -X POST http://127.0.0.1:3077/v1/images/generations "
        "-H 'Content-Type: application/json' -H 'Authorization: Bearer %s' "
        "-d '{\"model\":\"gpt-image-2.5\",\"prompt\":\"a cute cat\",\"n\":1,\"size\":\"1024x1024\"}'" % AUTH,
        timeout=220,
    )
    dt = time.time() - t0
    if '"b64_json"' in o or '"url"' in o:
        tag = "OK"
    elif "image_quota_exhausted" in o:
        tag = "QUOTA"
    elif "unsupported_model" in o:
        tag = "404"
    elif "no_available_account" in o:
        tag = "NOACC"
    else:
        tag = "OTHER"
    print("  [%d/3] %-5s %.1fs %s" % (i + 1, tag, dt, o[:130].replace("\n", " ")))
    if tag == "QUOTA" or tag == "NOACC":
        break  # 配额未恢复则不浪费尝试

# 2. 文本链路
print("== TEXT (gpt-4o) ==")
t0 = time.time()
o, e = run(
    "curl -s -m 120 -X POST http://127.0.0.1:3077/v1/chat/completions "
    "-H 'Content-Type: application/json' -H 'Authorization: Bearer %s' "
    "-d '{\"model\":\"gpt-4o\",\"messages\":[{\"role\":\"user\",\"content\":\"say hi\"}]}'" % AUTH,
    timeout=150,
)
dt = time.time() - t0
ok = '"content"' in o and "choices" in o
print("  %s %.1fs %s" % ("OK" if ok else "FAIL", dt, o[:130].replace("\n", " ")))
