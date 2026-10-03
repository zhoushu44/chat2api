#!/bin/bash
set -u
docker cp /tmp/fix_config.py regiforge:/tmp/fix_config.py
docker exec regiforge python3 /tmp/fix_config.py
echo ""
echo "=== 验证新配置 ==="
docker exec regiforge python3 -c "
import json
d = json.load(open('/app/data/config.json'))
for pid in ('wary','socks5'):
    print(pid, '->', d['proxy'][pid].get('api_url'))
import json as j
raw = j.dumps(d)
print('remaining 192.6.121.16 refs:', raw.count('192.6.121.16'))
"
