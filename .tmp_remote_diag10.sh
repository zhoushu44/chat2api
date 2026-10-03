#!/bin/bash
# 第十轮：完整 HTTP 响应计时（模拟真实注册请求路径）+ 查项目代理配置
set -u

echo "===== A. 容器内：走 warp 池出口请求 auth.openai.com 完整响应计时 ====="
docker exec chatgpt2api-13 python3 -c "
import socks, socket, ssl, time

for port in (10045, 10010, 10011):
    t0 = time.time()
    try:
        s = socks.socksocket()
        s.set_proxy(socks.SOCKS5, '195.72.185.32', port, rdns=True, username='warpuser', password='test-pass-123')
        s.settimeout(30)
        s.connect(('auth.openai.com', 443))
        t_conn = time.time() - t0
        ctx = ssl.create_default_context()
        w = ctx.wrap_socket(s, server_hostname='auth.openai.com')
        w.settimeout(30)
        t_tls = time.time() - t0
        w.sendall(b'GET / HTTP/1.1\r\nHost: auth.openai.com\r\nUser-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36\r\nAccept: */*\r\nConnection: close\r\n\r\n')
        resp = b''
        while len(resp) < 400:
            chunk = w.recv(400)
            if not chunk: break
            resp += chunk
        t_done = time.time() - t0
        status = resp.split(b'\r\n',1)[0][:60]
        print(f'port {port}: conn={t_conn:.1f}s tls={t_tls:.1f}s full={t_done:.1f}s status={status}')
        w.close()
    except Exception as e:
        print(f'port {port}: FAIL after {time.time()-t0:.1f}s {type(e).__name__}: {e}')
" 2>&1

echo ""
echo "===== B. 容器内：请求 chatgpt.com 完整响应计时 ====="
docker exec chatgpt2api-13 python3 -c "
import socks, socket, ssl, time
for port in (10045,):
    t0 = time.time()
    try:
        s = socks.socksocket()
        s.set_proxy(socks.SOCKS5, '195.72.185.32', port, rdns=True, username='warpuser', password='test-pass-123')
        s.settimeout(40)
        s.connect(('chatgpt.com', 443))
        t_conn = time.time() - t0
        ctx = ssl.create_default_context()
        w = ctx.wrap_socket(s, server_hostname='chatgpt.com')
        w.settimeout(40)
        t_tls = time.time() - t0
        w.sendall(b'GET / HTTP/1.1\r\nHost: chatgpt.com\r\nUser-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36\r\nConnection: close\r\n\r\n')
        resp = b''
        while len(resp) < 400:
            chunk = w.recv(400)
            if not chunk: break
            resp += chunk
        t_done = time.time() - t0
        status = resp.split(b'\r\n',1)[0][:60]
        print(f'chatgpt.com port {port}: conn={t_conn:.1f}s tls={t_tls:.1f}s full={t_done:.1f}s status={status}')
    except Exception as e:
        print(f'chatgpt.com port {port}: FAIL after {time.time()-t0:.1f}s {type(e).__name__}: {e}')
" 2>&1

echo ""
echo "===== C. 项目注册配置（projects 段 + 完整 proxy 段落名） ====="
docker exec chatgpt2api-13 python3 -c "
import json
d = json.load(open('/opt/regiforge/data/config.json'))
print('top-level keys:', list(d.keys()))
p = d.get('projects') or {}
print('projects keys:', list(p.keys()) if isinstance(p, dict) else type(p))
import sys
cr = p.get('chatgpt_register') if isinstance(p, dict) else None
if cr:
    def mask(o):
        if isinstance(o, dict):
            return {k: ('***' if any(s in k.lower() for s in ('token','key','secret','password')) else mask(v)) for k,v in o.items()}
        return o
    print(json.dumps(mask(cr), indent=1, ensure_ascii=False)[:2000])
" 2>&1

echo ""
echo "===== D. 当前任务列表（:3077 API 正确路径） ====="
docker exec chatgpt2api-13 sh -c "curl -s --max-time 5 http://127.0.0.1:8787/api/tasks 2>/dev/null | head -c 600" 2>&1
echo ""
curl -s --max-time 5 "http://127.0.0.1:3077/api/tasks" 2>/dev/null | head -c 600
echo ""
