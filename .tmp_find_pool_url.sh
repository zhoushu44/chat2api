#!/bin/bash
set -u
echo "=== regiforge 容器的 data 挂载与配置 ==="
docker inspect regiforge --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}
{{end}}'
echo "=== regiforge 容器内 wary/socks5 配置 ==="
docker exec regiforge python3 -c "
import json
d = json.load(open('/app/data/config.json'))
for pid in ('wary','socks5'):
    c = d.get('proxy',{}).get(pid,{})
    print(f'--- {pid} ---')
    print('api_url:', c.get('api_url'))
    print('api_key:', (c.get('api_key') or '')[:6]+'...' if c.get('api_key') else '(empty)')
    print('timeout:', c.get('timeout'))
"
echo ""
echo "=== 192.6.121.16:4433 通不通（regiforge 容器内） ==="
docker exec regiforge sh -c "timeout 8 curl -s -o /dev/null -w 'HTTP %{http_code} in %{time_total}s\n' http://192.6.121.16:4433/api/pool/status 2>&1 || echo TIMEOUT"
echo ""
echo "=== 从宿主机也测 ==="
timeout 8 curl -s -o /dev/null -w "HTTP %{http_code} in %{time_total}s\n" http://192.6.121.16:4433/api/pool/status 2>&1 || echo "TIMEOUT"
