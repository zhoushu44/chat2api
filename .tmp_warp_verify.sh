#!/bin/bash
set -u
echo "=== 1. unhealthy 实例清单 ==="
curl -s --max-time 10 "http://195.72.185.32:4433/api/pool/status" | tr '{' '\n' | grep -E '"health":"unhealthy"' | grep -oE '"container":"[^"]*"|"instance_index":[0-9]+|"host_port":[0-9]+|"health":"[^"]*"' | paste - - - - | head -10
echo ""
echo "=== 2. 含 unhealthy 判定的日志 ==="
docker logs warp --since 15m 2>&1 | grep -E "不健康|unhealthy" | tail -8
echo ""
echo "=== 3. 新功能验证：引擎自愈代码路径是否可被调用（检查 API 是否接受 failure_type） ==="
curl -s --max-time 8 -X POST "http://195.72.185.32:4433/api/pool/report" -H "Content-Type: application/json" -d '{"session_id":"nonexistent-test","failure_type":"proxy_dead"}' | head -c 200
echo ""
echo "（预期：session_id 不存在 —— 说明 failure_type 参数已被正确接收，未因缺 result 报错）"
