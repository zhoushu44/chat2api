# -*- coding: utf-8 -*-
"""查 400 响应 + 归因统计（base64 中转 python 脚本）"""
import sys, json, base64
sys.path.insert(0, r"e:\360MoveData\Users\Administrator\Desktop\chat2api")
from _s import run

# 1. 服务器端 python 脚本：归因统计
PY = '''
import json
from collections import Counter
accs, codes, fails = Counter(), Counter(), Counter()
with open("/data/image_attempts.jsonl") as f:
    lines = f.readlines()
for l in lines[-80:]:
    d = json.loads(l)
    codes[d["status"]] += 1
    for a in d["attempts"]:
        accs[a["account_id"]] += 1
        if a["code"] != "ok":
            fails[a["code"]] += 1
print("recent80 status:", dict(codes))
print("recent80 accounts(%d):" % len(accs), dict(accs.most_common(40)))
print("recent80 fail codes:", dict(fails))
'''
b64 = base64.b64encode(PY.encode()).decode()
o, e = run('docker exec chatgpt2api-14 sh -c "echo %s | base64 -d > /tmp/attr.py && python3 /tmp/attr.py"' % b64, timeout=60)
print("ATTRIBUTION:\n", o, e[:300])

# 2. 找 400：检查 .out 文件里不含 b64_json 的
PY2 = '''
import glob
for f in sorted(glob.glob("/tmp/img_*.out")):
    try:
        head = open(f, "rb").read(300).decode("utf-8", "replace")
    except Exception:
        continue
    if "b64_json" not in head:
        print(f, "=>", head[:250])
'''
b64 = base64.b64encode(PY2.encode()).decode()
o, e = run('docker exec chatgpt2api-14 sh -c "echo %s | base64 -d > /tmp/find400.py && python3 /tmp/find400.py"' % b64, timeout=60)
print("NON-OK:\n", o, e[:300])
