#!/bin/bash
# 第十五轮 b：把 python 写进容器文件再执行（避开 heredoc 管道问题）
set -u

cat > /tmp/diag15.py << 'PYEOF'
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

print('--- sid session ports (real registration path) ---', flush=True)
for sid in ('chatgpt-z1','chatgpt-z2','chatgpt-z3','chatgpt-z4'):
    port = get_proxy(sid)
    if port:
        print(f'sid {sid} (port {port}): {test(port)}', flush=True)
    else:
        print(f'sid {sid}: acquire failed', flush=True)

print('', flush=True)
print('--- base pool ports (10010-10016, no sid) ---', flush=True)
for port in (10010,10011,10012,10013,10014,10015,10016):
    print(f'port {port}: {test(port)}', flush=True)
PYEOF

docker cp /tmp/diag15.py chatgpt2api-13:/tmp/diag15.py
docker exec chatgpt2api-13 python3 /tmp/diag15.py 2>&1
