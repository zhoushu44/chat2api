#!/bin/bash
# 第十五轮：粘性 sid 会话端口 vs 基础池端口 深度对比（时间分布 + 多端口）
set -u

echo "===== A. 容器内对比：sid 会话端口（注册实际拿到的） ====="
docker exec chatgpt2api-13 python3 << 'PYEOF'
import socks, socket, ssl, time, subprocess, json

def get_proxy(sid):
    out = subprocess.run(['curl','-s','--max-time','15',
                          f'http://195.72.185.32:4433/api/proxies?num=1&type=json&format=n&sid={sid}&time=20'],
                         capture_output=True, text=True).stdout
    try:
        d = json.loads(out)
        p = (d.get('data') or {}).get('proxies') or [{}]
        return int(str(p[0].get('proxy','')).rsplit(':',1)[1])
    except Exception:
        return None

def test(port, host='sentinel.openai.com', timeout=30):
    t0=time.time()
    try:
        s = socks.socksocket()
        s.set_proxy(socks.SOCKS5, '195.72.185.32', port, rdns=True, username='warpuser', password='test-pass-123')
        s.settimeout(timeout)
        s.connect((host, 443))
        t_c = time.time()-t0
        ctx = ssl.create_default_context()
        w = ctx.wrap_socket(s, server_hostname=host)
        w.settimeout(timeout)
        t_t = time.time()-t0
        w.sendall(f'GET /backend-api/sentinel/frame.html HTTP/1.1\r\nHost: {host}\r\nUser-Agent: Mozilla/5.0\r\nConnection: close\r\n\r\n'.encode())
        resp = b''
        while len(resp) < 300:
            c = w.recv(300)
            if not c: break
            resp += c
        t_d = time.time()-t0
        line = resp.split(b'\r\n',1)[0] if resp else b'(EMPTY)'
        return f'conn={t_c:.1f}s tls={t_t:.1f}s full={t_d:.1f}s -> {line[:40].decode(errors="replace")}'
    except Exception as e:
        return f'FAIL {time.time()-t0:.1f}s {type(e).__name__}: {str(e)[:80]}'

print('--- sid 会话端口（注册真实路径）---')
for sid in ('chatgpt-y1','chatgpt-y2','chatgpt-y3','chatgpt-y4'):
    port = get_proxy(sid)
    if port:
        print(f'sid {sid} (port {port}): {test(port)}')
    else:
        print(f'sid {sid}: 获取失败')

print('')
print('--- 基础池端口（10010-10016，无 sid）---')
for port in (10010,10011,10012,10013,10014,10015,10016):
    print(f'port {port}: {test(port)}')
PYEOF
