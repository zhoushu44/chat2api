#!/in/bash
# 第二十三轮：最终复现 —— 用与注册完全一致的「本地 HTTP 转发器」路径测试
set -u

cat > /tmp/diag23.py << 'PYEOF'
import sys, time
sys.path.insert(0, '/opt/regiforge')
from proxy.socks5.http_forwarder import Socks5HttpForwarder

# 与注册一致：带认证的 SOCKS5 → 本地 HTTP 转发器
f = Socks5HttpForwarder(
    remote_host='195.72.185.32',
    remote_port=10076,
    username='warpuser',
    password='test-pass-123',
)
local = f.start_sync()
print(f'forwarder listening at {local}', flush=True)

import socks, socket
# 通过本地转发器（HTTP CONNECT）发 HTTPS 请求
import http.client
from urllib.parse import urlparse

px = urlparse(local)
t0 = time.time()
try:
    # 先直接测 TCP 到转发器
    s = socket.create_connection((px.hostname, px.port), timeout=10)
    s.sendall(b'CONNECT sentinel.openai.com:443 HTTP/1.1\r\nHost: sentinel.openai.com:443\r\n\r\n')
    resp = b''
    while b'\r\n\r\n' not in resp:
        c = s.recv(200)
        if not c: break
        resp += c
    print(f'CONNECT handshake: {time.time()-t0:.1f}s -> {resp[:60]}', flush=True)
except Exception as e:
    print(f'CONNECT FAIL {time.time()-t0:.1f}s: {e}', flush=True)
PYEOF

docker cp /tmp/diag23.py chatgpt2api-13:/tmp/diag23.py
docker exec chatgpt2api-13 python3 /tmp/diag23.py 2>&1

echo ""
echo "===== B. curl_cffi 用 socks5h://user:pass@ 直连认证端口（注册的另一路径） ====="
cat > /tmp/diag23b.py << 'PYEOF'
from curl_cffi import requests as cr
import time
px = 'socks5h://warpuser:test-pass-123@195.72.185.32:10076'
t0 = time.time()
try:
    r = cr.get('https://sentinel.openai.com/backend-api/sentinel/frame.html',
               proxies={'http': px, 'https': px}, impersonate='chrome131', timeout=25)
    print(f'socks5h direct: {time.time()-t0:.1f}s HTTP {r.status_code} len={len(r.text)}')
except Exception as e:
    print(f'socks5h direct FAIL {time.time()-t0:.1f}s: {str(e)[:150]}')
PYEOF
docker cp /tmp/diag23b.py chatgpt2api-13:/tmp/diag23b.py
docker exec chatgpt2api-13 python3 /tmp/diag23b.py 2>&1
