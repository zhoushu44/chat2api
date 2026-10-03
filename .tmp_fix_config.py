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

email_sec = d.get('email', {})
for pid, cfg in email_sec.items():
    if isinstance(cfg, dict):
        val = cfg.get('proxy')
        if isinstance(val, str) and '192.6.121.16' in val:
            new = val.replace('192.6.121.16', '195.72.185.32')
            cfg['proxy'] = new
            changed.append(f'email.{pid}.proxy: {val} -> {new}')

# 全文兜底扫一遍（防止藏在别的段）
raw = json.dumps(d, ensure_ascii=False)
if '192.6.121.16' in raw:
    # 递归替换所有字符串值
    def walk(o):
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(x) for x in o]
        if isinstance(o, str) and '192.6.121.16' in o:
            changed.append(f'deep: {o[:80]}')
            return o.replace('192.6.121.16', '195.72.185.32')
        return o
    d = walk(d)

with open(path, 'w', encoding='utf-8') as f:
    json.dump(d, f, ensure_ascii=False, indent=2)

print('CHANGED:')
for c in changed:
    print(' ', c)
if not changed:
    print('  (nothing)')
