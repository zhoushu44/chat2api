# -*- coding: utf-8 -*-
"""压测后诊断：503 的具体错误内容 + 归因"""
import sys, base64
sys.path.insert(0, r"e:\360MoveData\Users\Administrator\Desktop\chat2api")
from _s import run

# 1. chat2api 服务日志（supervisord 管的 Go 进程日志）
o, e = run('docker exec chatgpt2api-14 sh -c "tail -30 /data/logs/*.log 2>/dev/null || ls /data/logs/ 2>/dev/null || echo NO_LOGS_DIR"', timeout=30)
print("LOGS:\n", o[-2000:], e[:200])

# 2. Go 进程 stdout（supervisord）
o, e = run('docker exec chatgpt2api-14 sh -c "tail -40 /var/log/supervisor/chatgpt2api*.log 2>/dev/null || ls /var/log/supervisor/ 2>/dev/null"', timeout=30)
print("SUP LOGS:\n", o[-2500:], e[:200])

# 3. 归因最近 100 条
PY = '''
import json
from collections import Counter
accs, codes, fails = Counter(), Counter(), Counter()
lines = open("/data/image_attempts.jsonl").readlines()
for l in lines[-120:]:
    d = json.loads(l)
    codes[d["status"]] += 1
    for a in d["attempts"]:
        accs[a["account_id"]] += 1
        if a["code"] != "ok":
            fails[a["code"]] += 1
print("recent120 status:", dict(codes))
print("accounts used(%d):" % len(accs), len(accs))
print("fail codes:", dict(fails.most_common(10)))
'''
b64 = base64.b64encode(PY.encode()).decode()
o, e = run('docker exec chatgpt2api-14 sh -c "echo %s | base64 -d > /tmp/attr.py && python3 /tmp/attr.py"' % b64, timeout=60)
print("ATTRIBUTION:\n", o, e[:200])
