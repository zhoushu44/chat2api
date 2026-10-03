#!/bin/bash
# 第二十五轮：验证假设 —— usque 引擎「进程在但隧道死」。直接测 usque 引擎端口
set -u

echo "===== A. 服务器本机直连各实例 usque 引擎（20000+idx）测出口连通性 ====="
cat > /tmp/d25.py << 'PYEOF'
import socks, socket, ssl, time

results = {'ok': 0, 'fail': 0, 'slow': 0}
def test_engine(idx, timeout=12):
    port = 20000 + idx
    t0 = time.time()
    try:
        s = socks.socksocket()
        # usque 引擎无认证
        s.set_proxy(socks.SOCKS5, '127.0.0.1', port, rdns=True)
        s.settimeout(timeout)
        s.connect(('sentinel.openai.com', 443))
        ctx = ssl.create_default_context()
        w = ctx.wrap_socket(s, server_hostname='sentinel.openai.com')
        w.settimeout(timeout)
        return time.time() - t0
    except Exception as e:
        return f'FAIL {type(e).__name__} {str(e)[:50]}'

for idx in (0, 5, 10, 30, 50, 66, 80, 95):
    r = test_engine(idx)
    if isinstance(r, float):
        print(f'engine {idx} (port {20000+idx}): {r:.1f}s OK')
    else:
        print(f'engine {idx} (port {20000+idx}): {r}')
PYEOF
docker cp /tmp/d25.py warp:/tmp/d25.py 2>/dev/null || cp /tmp/d25.py /root/d25.py
# usque 在宿主机跑，直接宿主 python3？宿主没有 python3，用容器跑但连 127.0.0.1 不行
# → usque 引擎监听 127.0.0.1，必须宿主执行。用 node 代替
cat > /root/d25.js << 'JSEOF'
const net = require('net');
const socks = require('/root/warp/node_modules/socks') if false;
JSEOF
# 更简单：宿主有 curl，用 curl --socks5-hostname 测 usque 引擎端口
for idx in 0 5 10 30 50 66 80 95; do
  P=$((20000 + idx))
  R=$(timeout 12 curl -s --socks5-hostname "127.0.0.1:$P" -o /dev/null -w "%{http_code} %{time_total}s" https://sentinel.openai.com/backend-api/sentinel/frame.html 2>&1)
  RC=$?
  echo "engine $idx (127.0.0.1:$P): exit=$RC [$R]"
done

echo ""
echo "===== B. usque 进程 CPU 时间戳（看是否真的在工作） ====="
ps -o pid,etime,time,cmd -C usque 2>/dev/null | head -8

echo ""
echo "===== C. engine.log 时间戳 vs 实际当前时间 ====="
date
tail -3 /root/warp-instances/warp-66/engine.log
