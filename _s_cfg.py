# -*- coding: utf-8 -*-
"""统计可用账号（容错版）"""
import sys, base64
sys.path.insert(0, r"e:\360MoveData\Users\Administrator\Desktop\chat2api")
from _s import run

PY = '''
import json, time
d = json.load(open("/data/accounts.json"))
ok = [k for k, v in d.items() if isinstance(v, dict) and v.get("status") == "正常"]
now = time.time()
cool = [k for k in ok if (d[k].get("cooldown_until") or 0) > now]
print("正常账号:", len(ok), "| 冷却中:", len(cool), "| 可立即用:", len(ok) - len(cool))
print("冷却样例:", [(k, int(d[k].get("cooldown_until", 0) - now)) for k in cool[:10]])
'''
b64 = base64.b64encode(PY.encode()).decode()
o, e = run('docker exec chatgpt2api-14 sh -c "echo %s | base64 -d > /tmp/cfgchk2.py && python3 /tmp/cfgchk2.py"' % b64, timeout=60)
print(o, e[:300])
