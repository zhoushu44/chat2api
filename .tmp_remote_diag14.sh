#!/bin/bash
# 第十四轮：锁定差异 —— sid 会话端口 vs 池基础端口（粘性会话的出口是否坏了）
set -u

KEY=$(docker exec chatgpt2api-13 python3 -c "
import json
d = json.load(open('/opt/regiforge/data/config.json'))
p = d.get('proxy', {})
for name, cfg in p.items():
    if isinstance(cfg, dict) and cfg.get('api_key'):
        print(cfg.get('api_key')); break
")
echo "key: $([ -n "$KEY" ] && echo found || echo MISSING)"

echo ""
echo "===== A. 取两个不同的 sid 会话代理（模拟注册逐号取新出口） ====="
for SID in aaa-1 bbb-2 ccc-3; do
  R=$(curl -s --max-time 15 -H "X-API-Key: $KEY" "http://195.72.185.32:4433/api/proxies?num=1&type=json&format=n&sid=chatgpt-$SID&time=20")
  PORT_=$(echo "$R" | grep -oE '"proxy":"socks5://195\.72\.185\.32:[0-9]+"' | grep -oE '[0-9]+"$' | tr -d '"')
  echo "sid=chatgpt-$SID -> auth port $PORT_"
done

echo ""
echo "===== B. 多个 sid 会话端口实测 sentinel.openai.com POST ====="
docker exec chatgpt2api-13 python3 << 'PYEOF'
import socks, socket, ssl, time, subprocess, json

def get_proxy(sid):
    out = subprocess.run(['curl','-s','--max-time','15','-H','X-API-Key: test-nokey-needed-local',
                          f'http://195.72.185.32:4433/api/proxies?num=1&type=json&format=n&sid={sid}&time=20'],
                         capture_output=True, text=True).stdout
    try:
        d = json.loads(out)
        p = (d.get('data') or {}).get('proxies') or [{}]
        return int(str(p[0].get('proxy','')).rsplit(':',1)[1])
    except Exception:
        return None

# 服务器上取 sid 代理（无 key 竟然也能取？先验证）
for sid in ('chatgpt-x1','chatgpt-x2'):
    port = get_proxy(sid)
    print(f'sid {sid} -> port {port}')
    if not port: continue
    t0=time.time()
    try:
        s = socks.socksocket()
        s.set_proxy(socks.SOCKS5, '195.72.185.32', port, rdns=True, username='warpuser', password='test-pass-123')
        s.settimeout(30)
        s.connect(('sentinel.openai.com', 443))
        ctx = ssl.create_default_context()
        w = ctx.wrap_socket(s, server_hostname='sentinel.openai.com')
        w.settimeout(30)
        w.sendall(b'GET /backend-api/sentinel/frame.html HTTP/1.1\r\nHost: sentinel.openai.com\r\nUser-Agent: Mozilla/5.0\r\nConnection: close\r\n\r\n')
        resp = b''
        while len(resp) < 400:
            c = w.recv(400)
            if not c: break
            resp += c
        line = resp.split(b'\r\n',1)[0] if resp else b'(empty)'
        print(f'  GET frame.html: {time.time()-t0:.1f}s -> {line[:50]}')
    except Exception as e:
        print(f'  FAIL {time.time()-t0:.1f}s {type(e).__name__}: {str(e)[:100]}')
PYEOF

echo ""
echo "===== C. 池 API 无 key 也能取？（安全设计如此）确认 sid 会话数 ====="
curl -s --max-time 10 "http://195.72.185.32:4433/api/pool/status" | head -c 300; echo ""
