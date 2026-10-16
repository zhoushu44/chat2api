# -*- coding: utf-8 -*-
"""在容器内跑压测（单 SSH 长连接，nohup 后台），轮询输出"""
import sys, time
sys.path.insert(0, r"e:\360MoveData\Users\Administrator\Desktop\chat2api")
from _s import run

conc = sys.argv[1] if len(sys.argv) > 1 else "20"
total = sys.argv[2] if len(sys.argv) > 2 else "40"

# 后台启动
o, e = run('docker exec chatgpt2api-14 sh -c "nohup python3 /tmp/bench.py %s %s > /tmp/bench.out 2>&1 & echo STARTED pid=$!"' % (conc, total), timeout=30)
print(o.strip(), e[:200])
