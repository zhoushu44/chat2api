#!/bin/bash
set -u
echo "=== 容器内直调池 API（带 key，type=json） ==="
KEY=$(docker exec chatgpt2api-13 python3 -c "import json; print(json.load(open('/opt/regiforge/data/config.json'))['proxy']['wary']['api_key'])")
echo "key: ${KEY:0:4}..."
docker exec chatgpt2api-13 sh -c "curl -s --max-time 12 -H 'X-API-Key: $KEY' 'http://195.72.185.32:4433/api/proxies?num=1&type=json&format=n&sid=chatgpt-cont-test-1&time=20' | head -c 300"
echo ""
echo "=== 容器内不带 key ==="
docker exec chatgpt2api-13 sh -c "curl -s --max-time 12 'http://195.72.185.32:4433/api/proxies?num=1&type=json&format=n&sid=chatgpt-cont-test-2&time=20' | head -c 300"
echo ""
echo "=== python httpx 版本（provider 用 httpx） ==="
docker exec chatgpt2api-13 python3 -c "import httpx; print(httpx.__version__)"
