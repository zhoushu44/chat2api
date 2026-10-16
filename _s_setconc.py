# -*- coding: utf-8 -*-
"""改 account.image_account_concurrency=2（原缺省=1），重启 Go 服务"""
import sys, base64
sys.path.insert(0, r"e:\360MoveData\Users\Administrator\Desktop\chat2api")
from _s import run

PY = '''
import json
p = "/data/config.json"
c = json.load(open(p))
acc = c.setdefault("account", {})
print("before:", json.dumps(acc, ensure_ascii=False))
acc["image_account_concurrency"] = 2
json.dump(c, open(p, "w"), ensure_ascii=False, indent=2)
c2 = json.load(open(p))
print("after:", json.dumps(c2["account"], ensure_ascii=False))
'''
b64 = base64.b64encode(PY.encode()).decode()
o, e = run('docker exec chatgpt2api-14 sh -c "echo %s | base64 -d > /tmp/setconc.py && python3 /tmp/setconc.py"' % b64, timeout=60)
print(o, e[:300])

# 重启 Go（supervisord autorestart）
o, e = run('docker exec chatgpt2api-14 sh -c "pkill -f chatgpt2api-go ; echo KILLED"', timeout=30)
print(o.strip(), e[:200])

import time
time.sleep(8)
o, e = run('docker exec chatgpt2api-14 sh -c "curl -s -o /dev/null -w \\"%{http_code}\\" http://127.0.0.1:3077/api/accounts -H \\"Authorization: Bearer zs1236547\\""', timeout=30)
print("3077 STATUS:", o.strip(), e[:200])
