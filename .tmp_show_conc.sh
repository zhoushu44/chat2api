#!/bin/bash
set -u
cat > /tmp/show_conc.py << 'PYEOF'
import json, urllib.request
d = json.load(urllib.request.urlopen('http://127.0.0.1:8787/api/tasks/c0f99162b738/logs', timeout=8))
lines = d.get('lines', [])
ok_emails, fails = [], []
cur = None
for l in lines:
    if '已保存 Key' in l or '成功 key=' in l:
        ok_emails.append(l[:110])
    if '失败 status=' in l:
        fails.append(l[:200])
print('=== 成功 ===')
for x in ok_emails: print(x)
print()
print('=== 失败分类 ===')
from collections import Counter
c = Counter()
for f in fails:
    if 'class=proxy_dead' in f: c['proxy_dead (引擎挂死/出口慢)'] += 1
    elif '邮箱验证码' in f or 'D0004' in f: c['邮箱收码失败 (MailNest)'] += 1
    elif 'class=navigation_wrong' in f: c['navigation_wrong'] += 1
    elif 'SentinelSDK 未出现' in f: c['SentinelSDK 不执行 (页面风控)'] += 1
    elif 'exception' in f: c['其他异常'] += 1
    else: c['其他'] += 1
for k, v in c.most_common():
    print(f'{v}  {k}')
PYEOF
docker cp /tmp/show_conc.py regiforge:/tmp/show_conc.py
docker exec regiforge python3 /tmp/show_conc.py
