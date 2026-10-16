# -*- coding: utf-8 -*-
"""诊断：为什么并发40只成功1张——看这轮 attempts 归因 + cooldownFor 分类逻辑"""
import sys, base64
sys.path.insert(0, r"e:\360MoveData\Users\Administrator\Desktop\chat2api")
from _s import run

PY = '''
import json
from collections import Counter
lines = open("/data/image_attempts.jsonl").readlines()
codes = Counter(); accs = Counter(); recent = []
for l in lines[-60:]:
    d = json.loads(l)
    recent.append(d["status"])
    for a in d["attempts"]:
        codes[a["code"]] += 1
        accs[a["account_id"]] += 1
print("last60 status:", Counter(recent))
print("attempt codes:", dict(codes))
print("accounts:", dict(accs.most_common(30)))
'''
b64 = base64.b64encode(PY.encode()).decode()
o, e = run('docker exec chatgpt2api-14 sh -c "echo %s | base64 -d > /tmp/diag.py && python3 /tmp/diag.py"' % b64, timeout=60)
print("DIAG:\n", o, e[:300])

# cooldownFor：各失败码的冷却时长
o, e = run('grep -n -A25 "func cooldownFor" /root/chat2api/internal/protocol/orchestrator.go', timeout=30)
print("COOLDOWN:\n", o, e[:200])
