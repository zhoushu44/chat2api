#!/bin/bash
set -u
CONF=/opt/regiforge/data/config.json

echo "=== 备份配置 ==="
cp "$CONF" "$CONF.bak-20261002-pool-url"
echo BACKUP_OK

echo "=== 替换池 API 地址 192.6.121.16 -> 195.72.185.32 ==="
docker exec regiforge python3 - << 'PYEOF'
import json

path = '/app/data/config.json'
with open(path, encoding='utf-8') as f:
    d = json.load(f)

changed = []
proxy_sec = d.get('proxy', {})
for pid, cfg in proxy_sec.items():
    if isinstance(cfg, dict):
        for key in ('api_url', 'server'):
            val = cfg.get(key)
            if isinstance(val, str) and '192.6.121.16' in val:
                new = val.replace('192.6.121.16', '195.72.185.32')
                cfg[key] = new
                changed.append(f'proxy.{pid}.{key}: {val} -> {new}')

# tempmail 的 proxy 也可能指向老地址
email_sec = d.get('email', {})
for pid, cfg in email_sec.items():
    if isinstance(cfg, dict):
        val = cfg.get('proxy')
        if isinstance(val, str) and '192.6.121.16' in val:
            new = val.replace('192.6.121.16', '195.72.185.32')
            cfg['proxy'] = new
            changed.append(f'email.{pid}.proxy: {val} -> {new}')

with open(path, 'w', encoding='utf-8') as f:
    json.dump(d, f, ensure_ascii=False, indent=2)

print('CHANGED:')
for c in changed:
    print(' ', c)
if not changed:
    print('  (nothing)')
PYEOF

echo ""
echo "=== 验证新配置 ==="
docker exec regiforge python3 -c "
import json
d = json.load(open('/app/data/config.json'))
for pid in ('wary','socks5'):
    print(pid, '->', d['proxy'][pid].get('api_url'))
"
echo ""
echo "=== 池连通性（新地址，regiforge 容器内） ==="
docker exec regiforge sh -c "timeout 8 curl -s -o /dev/null -w 'HTTP %{http_code} in %{time_total}s\n' http://195.72.185.32:4433/api/pool/status"
