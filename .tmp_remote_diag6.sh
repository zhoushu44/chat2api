#!/bin/bash
# 第六轮：定位代理池 API（195.72.185.32:4433，本机就是 wary 池服务器）+ 实测出口
set -u

echo "===== A. :4433 是谁（本机代理池 API） ====="
ss -tlnp | grep -E ":4433" | head -5
docker ps --format '{{.Names}} {{.Ports}}' | grep -E "4433|proxypilot|wary" || true
echo ""
echo "--- proxypilot 容器（8765 端口）---"
docker ps --format '{{.Names}}' | grep -i proxypilot

echo ""
echo "===== B. 调 wary 池 API 实测取一个代理 ====="
KEY=$(docker exec chatgpt2api-13 python3 -c "import json; print(json.load(open('/opt/regiforge/data/config.json'))['proxy']['socks5']['api_key'])" 2>/dev/null)
echo "api_key obtained: $([ -n "$KEY" ] && echo yes || echo no)"
RESP=$(curl -s --max-time 15 -H "X-API-Key: $KEY" "http://195.72.185.32:4433/api/proxies?num=1&type=json&format=n&sid=chatgpt-diag-test-1&time=20")
echo "API response (first 500 chars): ${RESP:0:500}"
echo ""

echo "===== C. 用取到的代理实测出口连通性 ====="
# 解析 proxy 字段
PROXY_LINE=$(echo "$RESP" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    ps=(d.get('data') or {}).get('proxies') or []
    if ps:
        print(ps[0].get('proxy') or '')
except Exception:
    pass" 2>/dev/null)
echo "proxy acquired: $PROXY_LINE"

if [ -n "$PROXY_LINE" ]; then
  # 解析 host:port
  PP=${PROXY_LINE#socks5://}; PP=${PP#http://}
  HOST_=$(echo "$PP" | cut -d: -f1)
  PORT_=$(echo "$PP" | cut -d: -f2)
  echo "testing socks5 $HOST_:$PORT_ ..."
  # 服务器上没有 socks 支持的 curl？先看版本
  curl --version | head -1
  # 实测（SOCKS5）到 auth.openai.com
  timeout 30 curl -s --socks5-hostname "$HOST_:$PORT_" -o /dev/null -w "auth.openai.com via pool proxy: HTTP %{http_code} total=%{time_total}s\n" https://auth.openai.com/ 2>&1 || echo "TIMEOUT/FAIL"
  timeout 30 curl -s --socks5-hostname "$HOST_:$PORT_" https://ipinfo.io/json 2>/dev/null | head -c 250; echo ""
fi

echo ""
echo "===== D. 代理池服务器状态统计 ====="
curl -s --max-time 10 -H "X-API-Key: $KEY" "http://195.72.185.32:4433/api/pool/status" 2>/dev/null | head -c 800; echo ""
curl -s --max-time 10 -H "X-API-Key: $KEY" "http://195.72.185.32:4433/api/pool/sessions" 2>/dev/null | head -c 800; echo ""

echo ""
echo "===== E. chatgpt2api-13 内 python 出口测试（模拟 regiforge 用法） ====="
docker exec chatgpt2api-13 python3 -c "
import socket, socks, sys
# 从池里取的代理参数
host='$HOST_'; port=int('$PORT_' or 0)
if not host or not port:
    print('no proxy to test'); sys.exit(0)
s = socks.socksocket()
s.set_proxy(socks.SOCKS5, host, port, rdns=True)
s.settimeout(15)
try:
    s.connect(('auth.openai.com', 443))
    print('SOCKS5 connect auth.openai.com:443 OK')
except Exception as e:
    print(f'SOCKS5 connect FAIL: {e}')
s.close()
" 2>&1
