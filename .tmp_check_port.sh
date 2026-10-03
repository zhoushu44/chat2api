#!/bin/bash
set -u
echo "=== TXT 格式返回什么端口 ==="
curl -s --max-time 10 "http://195.72.185.32:4433/api/proxies?num=1&type=txt&format=n&sid=chatgpt-port-test-1&time=20"
echo ""
echo "=== JSON 格式返回什么端口 ==="
curl -s --max-time 10 "http://195.72.185.32:4433/api/proxies?num=1&type=json&format=n&sid=chatgpt-port-test-2&time=20" | head -c 400
echo ""
