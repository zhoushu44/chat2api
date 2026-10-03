#!/bin/bash
set -u
echo "=== docker logs 尾部 40 行 ==="
docker logs chatgpt2api-13 --tail 40 2>&1 | head -45
