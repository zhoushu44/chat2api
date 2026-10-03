#!/bin/bash
# 第十三轮：复现注册时真实的本地转发端口 —— 从池 API 取代理（跟注册流程一模一样的路径）
set -u

KEY=$(docker exec chatgpt2api-13 python3 -c "
import json
d = json.load(open('/opt/regiforge/data/config.json'))
p = d.get('proxy', {})
s5 = p.get('socks5', {})
print(s5.get('api_key') or '')
")
echo "api_key: $([ -n "$KEY" ] && echo found || echo MISSING)"

# 与注册一致：取一个 sid 会话（白名单/认证端口都测）
RESP=$(curl -s --max-time 15 -H "X-API-Key: $KEY" "http://195.72.185.32:4433/api/proxies?num=1&type=json&format=n&sid=chatgpt-diagrepro-77&time=20")
echo "pool response: ${RESP:0:400}"
echo ""

echo "===== 用取到的『认证端口』直接测（不经 forwarder） ====="
docker exec chatgpt2api-13 python3 -c "
import json, subprocess
resp = '''$RESP'''
d = json.loads(resp)
p = (d.get('data') or {}).get('proxies') or [{}]
if not p:
    print('no proxy returned')
else:
    import socks, socket, ssl, time
    # 认证端口
    auth_port = int(str(p[0].get('proxy','')).rsplit(':',1)[1])
    user = p[0].get('username')
    pw = p[0].get('password')
    print(f'auth port: {auth_port}, user: {user}')
    for port in (auth_port,):
        t0=time.time()
        try:
            s = socks.socksocket()
            s.set_proxy(socks.SOCKS5, '195.72.185.32', port, rdns=True, username=user, password=pw)
            s.settimeout(25)
            s.connect(('sentinel.openai.com', 443))
            ctx = ssl.create_default_context()
            w = ctx.wrap_socket(s, server_hostname='sentinel.openai.com')
            w.settimeout(25)
            w.sendall(b'POST /backend-api/sentinel/req HTTP/1.1\r\nHost: sentinel.openai.com\r\nContent-Type: text/plain;charset=UTF-8\r\nOrigin: https://sentinel.openai.com\r\nReferer: https://sentinel.openai.com/backend-api/sentinel/frame.html\r\nUser-Agent: Mozilla/5.0\r\nContent-Length: 50\r\nConnection: close\r\n\r\n{\"p\":\"gAAAAACtest\",\"id\":\"x\",\"flow\":\"main\"}')
            resp2 = b''
            while len(resp2) < 500:
                c = w.recv(500)
                if not c: break
                resp2 += c
            print(f'POST sentinel/req: {time.time()-t0:.1f}s -> {resp2.split(chr(13).encode(),1)[0][:50]}')
        except Exception as e:
            print(f'port {port}: FAIL {time.time()-t0:.1f}s {type(e).__name__}: {str(e)[:100]}')
"
