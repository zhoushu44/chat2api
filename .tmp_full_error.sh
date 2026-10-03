#!/bin/bash
set -u
echo "=== docker logs 里 7f354d7e2638 的完整错误 ==="
docker logs chatgpt2api-13 --since 10m 2>&1 | grep -A 2 "7f354d7e2638" | grep -E "异常|失败|Wary" | head -10
echo ""
echo "=== 完整一行（不截断） ==="
docker logs chatgpt2api-13 --since 10m 2>&1 | grep "7f354d7e2638.*异常" | head -3
