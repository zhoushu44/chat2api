#!/bin/bash
set -u
echo "=== /api/start 参数格式（从 server.js 提取） ==="
docker exec warp sh -c "grep -n \"app.post('/api/start'\" -A 25 /app/server.js | head -30"
