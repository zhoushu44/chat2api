#!/bin/bash
set -u
cat > /tmp/t_final.py << 'PYEOF'
import json, urllib.request, socks, ssl, time

ok = 0; fail = 0
for i in range(5):
    url = f'http://195.72.185.32:4433/api/proxies?num=1&type=json&format=n&sid=verify-final-{i}&time=20'
    r = json.load(urllib.request.urlopen(url, timeout=15))
    p = (r.get('data') or {}).get('proxies') or [{}]
    user = p[0].get('username'); pw = p[0].get('password')
    auth_port = int(str(p[0].get('proxy','')).rsplit(':',1)[1])
    t0 = time.time()
    try:
        s = socks.socksocket()
        s.set_proxy(socks.SOCKS5, '195.72.185.32', auth_port, rdns=True, username=user, password=pw)
        s.settimeout(25)
        s.connect(('auth.openai.com', 443))
        ctx = ssl.create_default_context()
        w = ctx.wrap_socket(s, server_hostname='auth.openai.com')
        w.settimeout(25)
        w.sendall(b'GET / HTTP/1.1\r\nHost: auth.openai.com\r\nUser-Agent: Mozilla/5.0\r\nConnection: close\r\n\r\n')
        resp = w.recv(200)
        st = resp.split(b'\r\n',1)[0].decode(errors='replace')[:30] if resp else '(empty)'
        print(f'  [{i}] port={auth_port} {time.time()-t0:.1f}s {st}')
        ok += 1
        s.close()
    except Exception as e:
        print(f'  [{i}] port={auth_port} FAIL {time.time()-t0:.1f}s {type(e).__name__}')
        fail += 1
print(f'\n结果: OK={ok} FAIL={fail}')
PYEOF
docker cp /tmp/t_final.py regiforge:/tmp/t_final.py
docker exec regiforge python3 /tmp/t_final.py

echo ""
echo "=== 自愈日志（新功能是否被触发） ==="
docker logs warp --since 40m 2>&1 | grep -E "引擎已重启|故障释放|重启引擎" | tail -5
echo "(若为空说明未触发——正常，因为没有失败上报)"

echo ""
echo "=== 池最终状态 ==="
curl -s --max-time 10 "http://195.72.185.32:4433/api/pool/status" | grep -oE '"total":[0-9]+|"available":[0-9]+|"in_use":[0-9]+|"unhealthy":[0-9]+' | head -4
