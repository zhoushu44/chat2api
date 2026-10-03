#!/bin/bash
set -u
echo "=== 1. unhealthy 清单（4 个） ==="
curl -s --max-time 10 "http://195.72.185.32:4433/api/pool/status" | tr '{' '\n' | grep -E '"health":"unhealthy"' | grep -oE '"container":"[^"]*"|"host_port":[0-9]+' | paste - - | head -6
echo ""
echo "=== 2. 实测取代理 + 真连 OpenAI（端到端） ==="
cat > /tmp/t_proxy.py << 'PYEOF'
import json, urllib.request, socks, socket, ssl, time

# 取一个代理
url = 'http://195.72.185.32:4433/api/proxies?num=1&type=json&format=n&sid=verify-10.0-test&time=20'
r = json.load(urllib.request.urlopen(url, timeout=15))
p = (r.get('data') or {}).get('proxies') or [{}]
port = p[0].get('port'); auth_port = int(str(p[0].get('proxy','')).rsplit(':',1)[1])
user = p[0].get('username'); pw = p[0].get('password')
print(f'acquired: port={port} auth_port={auth_port} exit_ip={p[0].get("exit_ip")}')

for host in ('sentinel.openai.com', 'auth.openai.com'):
    t0 = time.time()
    try:
        s = socks.socksocket()
        s.set_proxy(socks.SOCKS5, '195.72.185.32', auth_port, rdns=True, username=user, password=pw)
        s.settimeout(25)
        s.connect((host, 443))
        ctx = ssl.create_default_context()
        w = ctx.wrap_socket(s, server_hostname=host)
        print(f'  {host}: TLS OK ({time.time()-t0:.1f}s)')
        s.close()
    except Exception as e:
        print(f'  {host}: FAIL {time.time()-t0:.1f}s {type(e).__name__}')
PYEOF
docker cp /tmp/t_proxy.py regiforge:/tmp/t_proxy.py
docker exec regiforge python3 /tmp/t_proxy.py

echo ""
echo "=== 3. 新功能：自愈日志是否出现（ENGINE 重启） ==="
docker logs warp --since 30m 2>&1 | grep -E "引擎已重启|故障释放|连接失败 x" | tail -6
echo "(空 = 本轮恢复期间未触发自愈，属正常——无失败上报)"
