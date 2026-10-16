# -*- coding: utf-8 -*-
"""部署服务器端压测脚本到容器并运行（绕开本地 SSH 并发瓶颈）"""
import sys, json, base64, time
sys.path.insert(0, r"e:\360MoveData\Users\Administrator\Desktop\chat2api")
from _s import run

BENCH = '''
import json, threading, time, sys, urllib.request, urllib.error
from collections import Counter

CONC = int(sys.argv[1]) if len(sys.argv) > 1 else 20
TOTAL = int(sys.argv[2]) if len(sys.argv) > 2 else 40

PROMPTS = ["a flat minimalist icon of a %s, vector style" % w for w in [
    "camera","coffee cup","mountain","book","rocket","umbrella","headphone","piano",
    "leaf","cloud","anchor","compass","lightbulb","key","clock","envelope","globe",
    "flag","star","heart"]]

results = []
lock = threading.Lock()
t0 = time.time()

def one(i):
    body = json.dumps({"model":"gpt-image-2","prompt":PROMPTS[i%len(PROMPTS)],"n":1,"size":"1024x1024"}).encode()
    req = urllib.request.Request("http://127.0.0.1:3077/v1/images/generations", data=body, method="POST",
        headers={"Authorization":"Bearer zs1236547","Content-Type":"application/json"})
    ts = time.time()
    try:
        with urllib.request.urlopen(req, timeout=280) as r:
            code, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        code, raw = e.code, e.read()
    except Exception as e:
        code, raw = -1, str(e).encode()
    dur = time.time() - ts
    ok = code == 200 and b"b64_json" in raw[:2000]
    with lock:
        results.append((i, code, ok, dur))
        n = len(results)
        if n % 10 == 0 or n == TOTAL:
            print("progress %d/%d %.0fs" % (n, TOTAL, time.time()-t0), flush=True)

def worker(slot):
    for i in range(slot, TOTAL, CONC):
        one(i)

threads = [threading.Thread(target=worker, args=(s,)) for s in range(CONC)]
for t in threads: t.start()
for t in threads: t.join()
wall = time.time() - t0

codes = Counter(str(r[1]) for r in results)
oks = sum(1 for r in results if r[2])
durs = sorted(r[3] for r in results)
print("==== RESULT ====")
print("concurrency=%d total=%d success=%d wall=%.0fs" % (CONC, TOTAL, oks, wall))
print("codes:", dict(codes))
print("per-req: p50=%.0fs p90=%.0fs max=%.0fs" % (durs[len(durs)//2], durs[int(len(durs)*0.9)], durs[-1]))
for r in sorted(results, key=lambda x: -x[3])[:5]:
    print("slowest: idx=%d code=%s ok=%s dur=%.0fs" % r)
'''

b64 = base64.b64encode(BENCH.encode()).decode()
o, e = run('docker exec chatgpt2api-14 sh -c "echo %s | base64 -d > /tmp/bench.py && echo DEPLOYED"' % b64, timeout=60)
print(o.strip(), e[:200])
