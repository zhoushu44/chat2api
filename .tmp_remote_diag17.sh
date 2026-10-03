#!/bin/bash
# 第十七轮：锁定根因 —— 测 10045/10070 的白名单端口 + 无认证端口对照
set -u

echo "===== A. 三种端口类型对照测试（TLS 握手到 sentinel.openai.com） ====="
cat > /tmp/diag17.py << 'PYEOF'
import socks, socket, ssl, time, subprocess, json

def get_proxy(sid):
    out = subprocess.run(['curl','-s','--max-time','15',
                          f'http://195.72.185.32:4433/api/proxies?num=1&type=json&format=n&sid={sid}&time=20'],
                         capture_output=True, text=True).stdout
    try:
        d = json.loads(out)
        p = (d.get('data') or {}).get('proxies') or [{}]
        return {
            'auth': int(str(p[0].get('proxy','')).rsplit(':',1)[1]),
            'wl': int(str(p[0].get('proxy_whitelist','')).rsplit(':',1)[1]),
        }
    except Exception:
        return None

def tls_test(port, auth=True, timeout=20):
    t0=time.time()
    try:
        s = socks.socksocket()
        if auth:
            s.set_proxy(socks.SOCKS5, '195.72.185.32', port, rdns=True, username='warpuser', password='test-pass-123')
        else:
            s.set_proxy(socks.SOCKS5, '195.72.185.32', port, rdns=True)
        s.settimeout(timeout)
        s.connect(('sentinel.openai.com', 443))
        t_c = time.time()-t0
        ctx = ssl.create_default_context()
        w = ctx.wrap_socket(s, server_hostname='sentinel.openai.com')
        w.settimeout(timeout)
        return f'conn={t_c:.1f}s tls={time.time()-t0:.1f}s OK'
    except Exception as e:
        return f'FAIL {time.time()-t0:.1f}s {type(e).__name__}: {str(e)[:60]}'

# 1) sid 会话的认证端口 vs 白名单端口
info = get_proxy('chatgpt-final-a')
print(f'sid session: auth={info["auth"]} whitelist={info["wl"]}')
print(f'  auth port {info["auth"]}: {tls_test(info["auth"], auth=True)}')
print(f'  whitelist port {info["wl"]}: {tls_test(info["wl"], auth=False)}')

# 2) 已知基础端口（warp-0 实例，无 sid）对照
print(f'base port 10010 (no auth): {tls_test(10010, auth=False)}')
print(f'base port 10010 (with auth): {tls_test(10010, auth=True)}')
PYEOF

docker cp /tmp/diag17.py chatgpt2api-13:/tmp/diag17.py
docker exec chatgpt2api-13 python3 /tmp/diag17.py 2>&1

echo ""
echo "===== B. warp 容器内 sid 会话进程（sing-box 数量） ====="
docker exec warp sh -c "ps aux 2>/dev/null | head -3 || ls /proc | grep -cE '^[0-9]+$'"
echo "--- 服务器上监听 100xx 端口的 sing-box 进程 ---"
ss -tlnp | grep -E ":100[0-9][0-9]" | head -10

echo ""
echo "===== C. warp 管理端（node /app/server.cjs 是 :4433 池 API）sid 会话实现线索 ====="
ls -la /root/ 2>/dev/null | grep -iE "warp|pool" | head
docker inspect warp --format '{{json .Mounts}}' 2>/dev/null | head -c 500; echo ""
