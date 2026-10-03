#!/bin/bash
# 第十一轮：warp 池出口对 Cloudflare 的访问质量（是否被 CF 拉黑）+ 池健康统计 + 历史成功样本
set -u

echo "===== A. 容器内多端口实测 Cloudflare 质量指标 ====="
docker exec chatgpt2api-13 python3 -c "
import socks, socket, ssl, time

results = []
for port in (10010, 10011, 10045, 10046, 10012, 10013):
    t0 = time.time()
    try:
        s = socks.socksocket()
        s.set_proxy(socks.SOCKS5, '195.72.185.32', port, rdns=True, username='warpuser', password='test-pass-123')
        s.settimeout(25)
        s.connect(('www.cloudflare.com', 443))
        ctx = ssl.create_default_context()
        w = ctx.wrap_socket(s, server_hostname='www.cloudflare.com')
        w.settimeout(25)
        w.sendall(b'GET /cdn-cgi/trace HTTP/1.1\r\nHost: www.cloudflare.com\r\nUser-Agent: Mozilla/5.0\r\nConnection: close\r\n\r\n')
        resp = b''
        while True:
            chunk = w.recv(2000)
            if not chunk: break
            resp += chunk
            if len(resp) > 3000: break
        body = resp.split(b'\r\n\r\n',1)[1] if b'\r\n\r\n' in resp else b''
        loc = [l for l in body.decode(errors='replace').splitlines() if l.startswith('loc=')]
        wpo = [l for l in body.decode(errors='replace').splitlines() if l.startswith('warp=')]
        ip = [l for l in body.decode(errors='replace').splitlines() if l.startswith('ip=')]
        dt = time.time() - t0
        print(f'port {port}: {dt:.1f}s loc={loc[0] if loc else \"?\"} warp={wpo[0] if wpo else \"?\"} {ip[0][:28] if ip else \"\"}')
    except Exception as e:
        print(f'port {port}: FAIL {time.time()-t0:.1f}s {type(e).__name__}')
" 2>&1

echo ""
echo "===== B. warp 池 API 健康统计摘要 ====="
KEY=$(docker exec chatgpt2api-13 python3 -c "import json; print(json.load(open('/opt/regiforge/data/config.json'))['proxy']['socks5']['api_key'])" 2>/dev/null)
if [ -z "$KEY" ]; then
  # api_key 可能在别的字段，直接从 config 拿整段 socks5
  KEY=$(docker exec chatgpt2api-13 python3 -c "
import json
d = json.load(open('/opt/regiforge/data/config.json'))
p = d.get('proxy', {})
for name, cfg in p.items():
    if isinstance(cfg, dict) and cfg.get('api_key'):
        print(cfg.get('api_key')); break
" 2>/dev/null)
fi
echo "key found: $([ -n "$KEY" ] && echo yes || echo NO)"
curl -s --max-time 10 -H "X-API-Key: $KEY" "http://195.72.185.32:4433/api/pool/status" 2>/dev/null | python3 -m json.tool 2>/dev/null | grep -E '"(total|available|in_use|unhealthy)"' | head -6

echo ""
echo "===== C. 最近的成功任务 vs 失败任务分布 ====="
curl -s --max-time 5 "http://127.0.0.1:8787/api/tasks" 2>/dev/null | python3 -c "
import json,sys,time
tasks = json.load(sys.stdin)
now = time.time()
for t in tasks[:20]:
    age_min = (now - t.get('created_at',0))/60
    print(f\"{t['task_id'][:12]} state={t['state']:<8} ok={t.get('ok',0):<3} fail={t.get('failed',0):<3} done/total={t.get('done')}/{t.get('total')} created={age_min:.0f}min ago msg={t.get('message','')[:40]}\")
" 2>&1

echo ""
echo "===== D. warp 容器 IP_CHECK 失败率（最近日志统计） ====="
docker logs warp --since 3h 2>&1 | grep -cE "IP_CHECK.*失败|ERROR" || true
docker logs warp --since 3h 2>&1 | grep -E "ERROR" | tail -5
