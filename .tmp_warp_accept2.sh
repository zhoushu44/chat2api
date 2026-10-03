#!/bin/bash
set -u
cat > /tmp/t_proxy2.py << 'PYEOF'
import json, urllib.request, socks, ssl, time

url = 'http://195.72.185.32:4433/api/proxies?num=1&type=json&format=n&sid=verify-1002-test&time=20'
r = json.load(urllib.request.urlopen(url, timeout=15))
p = (r.get('data') or {}).get('proxies') or [{}]
user = p[0].get('username'); pw = p[0].get('password')
auth_port = int(str(p[0].get('proxy','')).rsplit(':',1)[1])
print(f'auth_port={auth_port} exit_ip={p[0].get("exit_ip")}')

for host in ('sentinel.openai.com', 'auth.openai.com', 'chatgpt.com'):
    t0 = time.time()
    try:
        s = socks.socksocket()
        s.set_proxy(socks.SOCKS5, '195.72.185.32', auth_port, rdns=True, username=user, password=pw)
        s.settimeout(25)
        s.connect((host, 443))
        ctx = ssl.create_default_context()
        w = ctx.wrap_socket(s, server_hostname=host)
        w.settimeout(25)
        w.sendall(f'GET / HTTP/1.1\r\nHost: {host}\r\nUser-Agent: Mozilla/5.0\r\nConnection: close\r\n\r\n'.encode())
        resp = w.recv(200)
        status = resp.split(b'\r\n',1)[0].decode(errors='replace')[:40] if resp else '(empty)'
        print(f'  {host}: {time.time()-t0:.1f}s {status}')
        s.close()
    except Exception as e:
        print(f'  {host}: FAIL {time.time()-t0:.1f}s {type(e).__name__}: {str(e)[:60]}')
PYEOF
docker cp /tmp/t_proxy2.py regiforge:/tmp/t_proxy2.py
docker exec regiforge python3 /tmp/t_proxy2.py

echo ""
echo "=== 自愈触发记录 ==="
docker logs warp --since 30m 2>&1 | grep -E "引擎已重启|故障释放|重启引擎|连接失败 x" | tail -8
