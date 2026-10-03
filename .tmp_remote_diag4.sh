#!/bin/bash
# 第四轮：出口代理连通性测试 + 配置检查
set -u

echo "===== A. regiforge 配置（脱敏：只看 provider 与代理段） ====="
docker exec chatgpt2api-13 cat /opt/regiforge/data/config.json 2>/dev/null | python3 -c "
import json,sys
d = json.load(sys.stdin)
def mask(o, depth=0):
    if isinstance(o, dict):
        return {k: ('***' if any(s in k.lower() for s in ('token','key','secret','password','apikey')) else mask(v, depth+1)) for k,v in o.items()}
    if isinstance(o, list):
        return [mask(x, depth+1) for x in o[:3]] + (['...%d more' % (len(o)-3)] if len(o)>3 else [])
    return o
print(json.dumps(mask(d), indent=1, ensure_ascii=False))
" 2>/dev/null | head -80

echo ""
echo "===== B. 服务器当前活跃的本地代理监听端口（usque/sing-box/其他） ====="
ss -tlnp | grep -E "127.0.0.1:(3[0-9]{4}|4[0-9]{4})" | head -20
echo "--- 总监听数 ---"
ss -tln | grep -cE "127.0.0.1:(3[0-9]{4}|4[0-9]{4})"

echo ""
echo "===== C. 服务器直连测试 auth.openai.com（不走代理） ====="
timeout 20 curl -s -o /dev/null -w "direct auth.openai.com: HTTP %{http_code} | connect=%{time_connect}s total=%{time_total}s\n" https://auth.openai.com/ 2>&1 || echo "direct: TIMEOUT/FAIL"
timeout 20 curl -s https://ipinfo.io/json 2>/dev/null | head -c 300; echo ""

echo ""
echo "===== D. 通过 127.0.0.1 出口端口测试（挑 4 个活跃端口） ====="
for PORT in $(ss -tln | grep -oE "127.0.0.1:(3[0-9]{4}|4[0-9]{4})" | grep -oE "[0-9]+$" | head -4); do
  echo "--- exit port $PORT ---"
  timeout 15 curl -s -x "http://127.0.0.1:$PORT" https://ipinfo.io/json 2>/dev/null | head -c 200
  echo ""
  timeout 15 curl -s -o /dev/null -x "http://127.0.0.1:$PORT" -w "auth.openai.com via exit: HTTP %{http_code} | total=%{time_total}s\n" https://auth.openai.com/ 2>&1 || echo "auth.openai.com via exit $PORT: TIMEOUT/FAIL"
done

echo ""
echo "===== E. warp 容器日志（出口可能走 warp 池） ====="
docker logs warp --tail 15 2>&1 | head -20
