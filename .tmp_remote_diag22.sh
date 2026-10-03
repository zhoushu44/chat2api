#!/bin/bash
# 第二十二轮：singbox.json 读取（上面 python3 不在宿主？直接 cat）+ TCP 握手层面深挖
set -u

echo "===== A. warp-66 / warp-0 singbox.json（cat + diff） ====="
cat /root/warp-instances/warp-66/singbox.json | head -c 1500; echo ""; echo "---"
cat /root/warp-instances/warp-0/singbox.json | head -c 1500; echo ""

echo ""
echo "===== B. 对 10076 发起多次连接，观察 sing-box 日志 ====="
tail -5 /root/warp-instances/warp-66/singbox.log 2>/dev/null
echo "--- 发起测试连接 ---"
timeout 8 docker exec chatgpt2api-13 python3 -c "
import socks, socket
s = socks.socksocket()
s.set_proxy(socks.SOCKS5, '195.72.185.32', 10076, rdns=True, username='warpuser', password='test-pass-123')
s.settimeout(6)
try:
    s.connect(('sentinel.openai.com', 443)); print('connected')
except Exception as e:
    print('fail:', e)
" 2>&1
sleep 2
echo "--- singbox.log 新增 ---"
tail -15 /root/warp-instances/warp-66/singbox.log 2>/dev/null

echo ""
echo "===== C. whitelist 11076 同样测试对照 ====="
timeout 8 docker exec chatgpt2api-13 python3 -c "
import socks, socket
s = socks.socksocket()
s.set_proxy(socks.SOCKS5, '195.72.185.32', 11076, rdns=True)
s.settimeout(6)
try:
    s.connect(('sentinel.openai.com', 443)); print('whitelist connected OK')
except Exception as e:
    print('fail:', e)
" 2>&1
sleep 2
tail -5 /root/warp-instances/warp-66/singbox.log 2>/dev/null

echo ""
echo "===== D. 服务器本机直连 10076 vs 11076（排除容器网络因素） ====="
for P in 10076 11076; do
  timeout 10 curl -s --socks5-hostname "warpuser:test-pass-123@195.72.185.32:$P" -o /dev/null -w "port $P: HTTP %{http_code} %{time_total}s\n" https://sentinel.openai.com/backend-api/sentinel/frame.html 2>&1 || echo "port $P: curl exit $?"
done
