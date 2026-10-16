# -*- coding: utf-8 -*-
"""503 到底哪里返回的？跑一次真实请求抓响应体 + 找 orchestrator 目录结构"""
import sys, json, base64
sys.path.insert(0, r"e:\360MoveData\Users\Administrator\Desktop\chat2api")
from _s import run

# 1. orchestrator 目录结构
o, e = run('ls /root/chat2api/internal/protocol/ /root/chat2api/internal/backend/ 2>/dev/null', timeout=30)
print("DIRS:\n", o, e[:200])

# 2. 找 Generate 方法定义文件
o, e = run('grep -rln "func.*Generate" /root/chat2api/internal/protocol/ /root/chat2api/internal/backend/ 2>/dev/null | head', timeout=30)
print("GEN FILES:\n", o, e[:200])

# 3. 修改 bench：记录失败响应体前 200 字节，重跑并发 40 小批
BENCH2 = '''
import json, threading, time, sys, urllib.request, urllib.error
CONC, TOTAL = 40, 40
PROMPTS = ["a flat icon of a %s, vector style" % w for w in ["camera","cup","mountain","book","rocket","umbrella","headphone","piano","leaf","cloud","anchor","compass","bulb","key","clock","mail","globe","flag","star","heart"]]
results, lock = [], threading.Lock()
def one(i):
    body = json.dumps({"model":"gpt-image-2","prompt":PROMPTS[i%20],"n":1,"size":"1024x1024"}).encode()
    req = urllib.request.Request("http://127.0.0.1:3077/v1/images/generations", data=body, method="POST",
        headers={"Authorization":"Bearer zs1236547","Content-Type":"application/json"})
    ts = time.time()
    try:
        with urllib.request.urlopen(req, timeout=280) as r: code, raw = r.status, r.read()
    except urllib.error.HTTPError as e: code, raw = e.code, e.read()
    except Exception as e: code, raw = -1, str(e).encode()
    with lock:
        results.append((i, code, b"b64_json" in raw[:2000], time.time()-ts, raw[:220] if code != 200 else b""))
def worker(s):
    for i in range(s, TOTAL, CONC): one(i)
ts = [threading.Thread(target=worker, args=(s,)) for s in range(CONC)]
[t.start() for t in ts]; [t.join() for t in ts]
ok = sum(1 for r in results if r[2])
print("conc=40 total=40 ok=%d" % ok)
for r in sorted(results):
    if not r[2]: print("FAIL idx=%d code=%s dur=%.0fs body=%s" % (r[0], r[1], r[3], r[4][:200].decode("utf-8","replace")))
'''
b64 = base64.b64encode(BENCH2.encode()).decode()
o, e = run('docker exec chatgpt2api-14 sh -c "echo %s | base64 -d > /tmp/bench2.py && python3 /tmp/bench2.py"' % b64, timeout=600)
print("BENCH2:\n", o, e[:300])
