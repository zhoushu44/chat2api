#!/bin/bash
# 第九轮：SOCKS5 认证握手实测 —— warp 池用户名/密码是否匹配
set -u

echo "===== A. 用 python socks 库做完整 SOCKS5 认证 + 连 OpenAI（服务器上） ====="
python3 -c "
import socks, socket
for port in (10045, 10010):
    s = socks.socksocket()
    s.set_proxy(socks.SOCKS5, '195.72.185.32', port, rdns=True, username='warpuser', password='test-pass-123')
    s.settimeout(20)
    try:
        s.connect(('auth.openai.com', 443))
        print(f'port {port}: SOCKS5+auth OK -> auth.openai.com:443')
    except Exception as e:
        print(f'port {port}: FAIL {type(e).__name__}: {e}')
    s.close()
" 2>&1

echo ""
echo "===== B. 容器内同样测试（regiforge 实际运行环境） ====="
docker exec chatgpt2api-13 python3 -c "
import socks, socket
for port in (10045, 10010):
    s = socks.socksocket()
    s.set_proxy(socks.SOCKS5, '195.72.185.32', port, rdns=True, username='warpuser', password='test-pass-123')
    s.settimeout(20)
    try:
        s.connect(('auth.openai.com', 443))
        print(f'port {port}: SOCKS5+auth OK (in-container)')
    except Exception as e:
        print(f'port {port}: FAIL (in-container) {type(e).__name__}: {e}')
    s.close()
" 2>&1

echo ""
echo "===== C. 容器内 curl_cffi 风格的 HTTPS 请求（带 socks5 认证） ====="
docker exec chatgpt2api-13 python3 -c "
import socks, socket, ssl
s = socks.socksocket()
s.set_proxy(socks.SOCKS5, '195.72.185.32', 10045, rdns=True, username='warpuser', password='test-pass-123')
s.settimeout(25)
try:
    s.connect(('auth.openai.com', 443))
    ctx = ssl.create_default_context()
    ctx.set_alpn_protocols(['h2', 'http/1.1'])
    w = ctx.wrap_socket(s, server_hostname='auth.openai.com')
    w.sendall(b'GET / HTTP/1.1\r\nHost: auth.openai.com\r\nUser-Agent: Mozilla/5.0\r\nConnection: close\r\n\r\n')
    resp = w.recv(200)
    print('HTTPS via SOCKS5:', resp[:80])
except Exception as e:
    print('HTTPS FAIL:', type(e).__name__, e)
" 2>&1

echo ""
echo "===== D. warp 容器内确认 10045 端口存在且是 sing-box ====="
docker exec warp sh -c "ss -tlnp 2>/dev/null | grep 10045 || netstat -tlnp 2>/dev/null | grep 10045" 2>&1 | head -5
docker exec warp sh -c "ps aux | head -8" 2>&1
