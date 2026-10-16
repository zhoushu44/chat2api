# -*- coding: utf-8 -*-
"""看压测后池状态：可用数、冷却分布"""
import sys, base64
sys.path.insert(0, r"e:\360MoveData\Users\Administrator\Desktop\chat2api")
from _s import run

PY = '''
import json, time
d = json.load(open("/data/accounts.json"))
now = time.time()
ok = [k for k, v in d.items() if isinstance(v, dict) and v.get("status") == "正常"]
cool = [(k, int(d[k].get("cooldown_until", 0) - now)) for k in ok if (d[k].get("cooldown_until") or 0) > now]
print("正常:", len(ok), "| 冷却中:", len(cool), "| 可立即用:", len(ok) - len(cool))
print("冷却剩余秒分布:", sorted(c[1] for c in cool))
new = [k for k in ok if d[k].get("quota_unknown")]
newcool = [k for k, _ in cool if d.get(k, {}).get("quota_unknown")]
print("新号(quota_unknown):", len(new), "其中冷却:", len(newcool))
'''
b64 = base64.b64encode(PY.encode()).decode()
o, e = run('docker exec chatgpt2api-14 sh -c "echo %s | base64 -d > /tmp/chk.py && python3 /tmp/chk.py"' % b64, timeout=60)
print(o, e[:300])
