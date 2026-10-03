#!/bin/bash
# 第十二轮：直接实测 sentinel.openai.com（Sentinel V8 真正请求的域）
set -u

echo "===== A. 容器内经 warp 出口请求 sentinel.openai.com ====="
docker exec chatgpt2api-13 python3 -c "
import socks, socket, ssl, time

for port in (10010, 10045, 10046):
    t0 = time.time()
    try:
        s = socks.socksocket()
        s.set_proxy(socks.SOCKS5, '195.72.185.32', port, rdns=True, username='warpuser', password='test-pass-123')
        s.settimeout(25)
        s.connect(('sentinel.openai.com', 443))
        t_conn = time.time() - t0
        ctx = ssl.create_default_context()
        w = ctx.wrap_socket(s, server_hostname='sentinel.openai.com')
        w.settimeout(25)
        t_tls = time.time() - t0
        w.sendall(b'GET /backend-api/sentinel/frame.html HTTP/1.1\r\nHost: sentinel.openai.com\r\nUser-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36\r\nAccept: text/html,application/javascript,*/*;q=0.8\r\nConnection: close\r\n\r\n')
        resp = b''
        while len(resp) < 600:
            chunk = w.recv(600)
            if not chunk: break
            resp += chunk
        t_done = time.time() - t0
        status = resp.split(b'\r\n',1)[0][:60]
        body_peek = resp.split(b'\r\n\r\n',1)[1][:150] if b'\r\n\r\n' in resp else b''
        print(f'port {port}: conn={t_conn:.1f}s tls={t_tls:.1f}s full={t_done:.1f}s {status.decode()}')
        print(f'  body: {body_peek[:120]}')
        w.close()
    except Exception as e:
        print(f'port {port}: FAIL after {time.time()-t0:.1f}s {type(e).__name__}: {e}')
" 2>&1

echo ""
echo "===== B. 容器内 curl_cffi 复现（与注册同样的库+出口） ====="
docker exec chatgpt2api-13 python3 -c "
from curl_cffi import requests as cr
import time
for port in (10010, 10045):
    px = f'socks5://warpuser:test-pass-123@195.72.185.32:{port}'
    t0 = time.time()
    try:
        r = cr.get('https://sentinel.openai.com/backend-api/sentinel/frame.html',
                   proxies={'http': px, 'https': px},
                   impersonate='chrome131', timeout=30,
                   headers={'accept': 'text/html,application/javascript,*/*;q=0.8'})
        print(f'port {port}: {time.time()-t0:.1f}s HTTP {r.status_code} len={len(r.text)}')
    except Exception as e:
        print(f'port {port}: FAIL {time.time()-t0:.1f}s {type(e).__name__}: {str(e)[:120]}')
" 2>&1

echo ""
echo "===== C. 容器内 curl_cffi 到 auth.openai.com（浏览器回退路径） ====="
docker exec chatgpt2api-13 python3 -c "
from curl_cffi import requests as cr
import time
for port in (10010, 10045):
    px = f'socks5://warpuser:test-pass-123@195.72.185.32:{port}'
    t0 = time.time()
    try:
        r = cr.get('https://auth.openai.com/',
                   proxies={'http': px, 'https': px},
                   impersonate='chrome131', timeout=30)
        print(f'port {port}: {time.time()-t0:.1f}s HTTP {r.status_code} len={len(r.text)}')
    except Exception as e:
        print(f'port {port}: FAIL {time.time()-t0:.1f}s {type(e).__name__}: {str(e)[:120]}')
" 2>&1
