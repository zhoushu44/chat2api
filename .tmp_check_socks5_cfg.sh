#!/bin/bash
set -u
echo "=== socks5 provider 的 api_url/api_key 配置 ==="
docker exec chatgpt2api-13 python3 -c "
import json
d = json.load(open('/opt/regiforge/data/config.json'))
s5 = d.get('proxy', {}).get('socks5', {})
print('api_url:', repr(s5.get('api_url')))
print('api_key:', repr(s5.get('api_key'))[:20])
print('timeout:', s5.get('timeout'))
wary = d.get('proxy', {}).get('wary', {})
print('--- wary ---')
print('api_url:', repr(wary.get('api_url')))
print('api_key:', repr(wary.get('api_key'))[:20])
"
echo ""
echo "=== 池 API 现在通不通 ==="
curl -s --max-time 10 "http://195.72.185.32:4433/api/pool/status" | head -c 150
echo ""
echo "=== 从容器内请求 socks5 的 api_url ==="
docker exec chatgpt2api-13 sh -c "curl -s --max-time 10 'http://195.72.185.32:4433/api/proxies?num=1&type=txt&format=n&sid=chatgpt-test-1&time=20' | head -c 200"
echo ""
