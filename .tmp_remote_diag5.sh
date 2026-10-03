#!/bin/bash
# 第五轮：配置 + 出口端到端实测 + wary API 实测
set -u

echo "===== A. regiforge 配置（脱敏） ====="
docker exec chatgpt2api-13 python3 -c "
import json
d = json.load(open('/opt/regiforge/data/config.json'))
def mask(o):
    if isinstance(o, dict):
        return {k: ('***' if any(s in k.lower() for s in ('token','key','secret','password','apikey')) else mask(v)) for k,v in o.items()}
    if isinstance(o, list):
        return [mask(x) for x in o[:3]] + (['...'] if len(o)>3 else [])
    return o
print(json.dumps(mask(d), indent=1, ensure_ascii=False))
" 2>&1 | head -100

echo ""
echo "===== B. 容器内活跃的本地转发端口 ====="
docker exec chatgpt2api-13 ss -tlnp 2>/dev/null | grep 127.0.0.1 | head -30 || docker exec chatgpt2api-13 netstat -tlnp 2>/dev/null | grep 127.0.0.1 | head -30

echo ""
echo "===== C. 容器内通过活跃端口实测出口连通性 ====="
for PORT in $(docker exec chatgpt2api-13 ss -tln 2>/dev/null | grep -oE "127.0.0.1:[0-9]+" | grep -oE "[0-9]+$" | head -3); do
  echo "--- port $PORT ---"
  docker exec chatgpt2api-13 timeout 20 curl -s -x "http://127.0.0.1:$PORT" -o /dev/null -w "ipinfo: %{http_code} total=%{time_total}s\n" https://ipinfo.io/json 2>&1
  docker exec chatgpt2api-13 timeout 30 curl -s -x "http://127.0.0.1:$PORT" -o /dev/null -w "auth.openai.com: %{http_code} total=%{time_total}s\n" https://auth.openai.com/ 2>&1
done
