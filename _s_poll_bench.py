# -*- coding: utf-8 -*-
"""轮询容器内 bench 输出"""
import sys, time
sys.path.insert(0, r"e:\360MoveData\Users\Administrator\Desktop\chat2api")
from _s import run

for i in range(int(sys.argv[1]) if len(sys.argv) > 1 else 6):
    o, e = run('docker exec chatgpt2api-14 sh -c "cat /tmp/bench.out 2>/dev/null | tail -25"', timeout=30)
    print("--- poll %d (%s) ---" % (i, time.strftime("%H:%M:%S")))
    print(o.strip()[-1500:])
    if "==== RESULT ====" in o or "RESULT" in o:
        break
    time.sleep(60)
